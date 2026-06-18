"""D1 版本原子切换(finalize)集成测试(连 PG + Milvus;**免模型**——走 PG 冷备零重编码)。

不可达则 skip。seed 老/新两版(同 logical,新版 supersedes 老版),均以 effective 入库,跑 finalize:
验旧版 PG version_status/chunk_status + Milvus 标量均置 superseded(不删)、新版仍 effective、
默认检索不见旧版而 --include-superseded 可见、切换可重放幂等、无 supersedes 件 no-op。

§1.1/§7.2 版本生命周期扩展(abolished / upcoming + activate):同套合成冷备,验
- abolish_only 件 finalize → 旧版置 **abolished**(非 superseded);
- upcoming 新版(未来生效)finalize **不切换**旧版、其块默认不可见,
  经 ``activate`` 翻 effective 后才切换。
"""

import datetime

import pytest
from sqlalchemy import delete, text
from ulid import ULID

from common.pg_models import Chunk, Document, DocVersion, ImportBatch, PipelineEvent
from pipeline.config import load_config
from pipeline.index import corpus_rows
from pipeline.index.milvus_io import MilvusIO, dense_to_bytes, sparse_to_bytes
from pipeline.index.object_store import ObjectStore
from pipeline.index.pg_io import PgIO
from pipeline.meta.version_chain import live_status
from pipeline.stage_base import StageContext
from pipeline.stages import finalize
from pipeline.states import PipelineState as PS

DENSE = [float((i * 7) % 13) + 0.5 for i in range(1024)]
SPARSE = {"1": 0.9, "5": 0.3, "42": 0.6}


@pytest.fixture(scope="module")
def stack():
    cfg = load_config()
    pg = PgIO.from_config(cfg)
    try:
        with pg.session() as s:
            s.execute(text("select 1"))
    except Exception:
        pytest.skip("PG 不可达")
    mio = MilvusIO(cfg)
    try:
        mio.connect()
        mio.create_collection()
    except Exception:
        pytest.skip("Milvus 不可达")
    ctx = StageContext(config=cfg, object_store=ObjectStore.from_config(cfg), db=pg, milvus=mio)
    yield pg, mio, ctx
    mio.disconnect()


def _seed_pair(
    pg, mio, *, relation, new_status="effective", new_effective_date=None, new_chunk_status=None
):
    """seed 同 logical 老/新两版(各 1 块带合成冷备),新版 supersedes 老版。返回四元组。

    老版恒 INDEXED+effective;新版的关系/状态/生效日/块状态由入参定(默认 revise_replace 一族:
    effective + 块 effective)。Milvus 各按其 chunk_status 灌入(老版 effective,新版按
    ``new_chunk_status``,默认随 ``new_status``)。
    """
    bid, lid = "as_" + str(ULID()), str(ULID())
    old_dvid, new_dvid = str(ULID()), str(ULID())
    new_chunk_status = new_chunk_status or new_status

    def _seed_version(dvid, *, tag, supersedes, vstatus, rel, eff_date, cstatus):
        with pg.session() as s:
            s.add(
                DocVersion(
                    doc_version_id=dvid, logical_id=lid, batch_id=bid, source_format="docx",
                    source_hash="h" + dvid[:8], raw_object_key="k",
                    pipeline_status=PS.INDEXED.value, version_status=vstatus,
                    perm_tag="内部", biz_domain="DISCLOSURE", issuer="CSRC",
                    effective_date=eff_date, supersedes_version_id=supersedes, version_relation=rel,
                )
            )
            s.flush()
            # 同毫秒 ULID 仅末位不同 → 用 tag 前缀保证两版 chunk_id 不撞(devlog ULID 截断坑)
            s.add(
                Chunk(
                    chunk_id=(tag + dvid)[:24], doc_version_id=dvid, text="第一条 内容。",
                    clause_path="第一章/第一条", clause_path_norm="1/1", seq=1, page_start=1,
                    is_parent=False, is_table=False, chunk_status=cstatus,
                    dense_vec_cold=dense_to_bytes(DENSE), sparse_vec_cold=sparse_to_bytes(SPARSE),
                )
            )
        mio.upsert(corpus_rows.rows_from_cold(pg, dvid, cstatus))  # 模拟已索引

    with pg.session() as s:
        s.add(ImportBatch(batch_id=bid, source_dir="x"))
        s.add(Document(logical_id=lid, corpus_type="P-INT", title="信息披露办法"))
    _seed_version(
        old_dvid, tag="o", supersedes=None, vstatus="effective", rel=None,
        eff_date=None, cstatus="effective",
    )
    _seed_version(
        new_dvid, tag="n", supersedes=old_dvid, vstatus=new_status, rel=relation,
        eff_date=new_effective_date, cstatus=new_chunk_status,
    )
    mio.flush()
    return lid, bid, old_dvid, new_dvid


def _teardown_pair(pg, mio, lid, bid, dvids):
    for d in dvids:
        mio.delete(d)
    mio.flush()
    with pg.session() as s:
        for d in dvids:
            s.execute(delete(Chunk).where(Chunk.doc_version_id == d))
            s.execute(delete(PipelineEvent).where(PipelineEvent.doc_version_id == d))
            s.execute(delete(DocVersion).where(DocVersion.doc_version_id == d))
        s.execute(delete(Document).where(Document.logical_id == lid))
        s.execute(delete(ImportBatch).where(ImportBatch.batch_id == bid))


@pytest.fixture
def revision_pair(stack):
    """seed 同 logical 的老/新两版(均 INDEXED+effective,各 1 块带冷备),新版 supersedes 老版。"""
    pg, mio, ctx = stack
    lid, bid, old_dvid, new_dvid = _seed_pair(pg, mio, relation="revise_replace")
    yield pg, mio, ctx, old_dvid, new_dvid
    _teardown_pair(pg, mio, lid, bid, (old_dvid, new_dvid))


@pytest.fixture
def abolish_pair(stack):
    """新版 abolish_only、effective:finalize 应把旧版置 abolished(非 superseded)。"""
    pg, mio, ctx = stack
    lid, bid, old_dvid, new_dvid = _seed_pair(pg, mio, relation="abolish_only")
    yield pg, mio, ctx, old_dvid, new_dvid
    _teardown_pair(pg, mio, lid, bid, (old_dvid, new_dvid))


@pytest.fixture
def upcoming_pair(stack):
    """新版未来生效(version_status=upcoming、块 upcoming):finalize 不切换,旧版保 effective。"""
    pg, mio, ctx = stack
    future = datetime.date.today() + datetime.timedelta(days=30)
    lid, bid, old_dvid, new_dvid = _seed_pair(
        pg, mio, relation="revise_replace", new_status="upcoming", new_effective_date=future
    )
    yield pg, mio, ctx, old_dvid, new_dvid
    _teardown_pair(pg, mio, lid, bid, (old_dvid, new_dvid))


def _dvids(res) -> list[str]:
    return [h["doc_version_id"] for h in res.hits]


def test_finalize_switches_old_to_superseded(revision_pair):
    pg, mio, ctx, old_dvid, new_dvid = revision_pair
    result = finalize.run(ctx, new_dvid)
    assert result.switched and result.old_dvid == old_dvid

    # PG:旧版 + 其 chunk → superseded;新版仍 effective
    assert pg.get(DocVersion, old_dvid).version_status == "superseded"
    assert pg.get(DocVersion, new_dvid).version_status == "effective"
    assert all(c.chunk_status == "superseded" for c in pg.get_chunks(old_dvid))
    assert all(c.chunk_status == "effective" for c in pg.get_chunks(new_dvid))

    # Milvus:旧版未删(标量改 superseded)——默认检索不见旧版,--include-superseded 可见;新版始终可见
    mio.flush()
    assert mio.count(old_dvid) == 1  # 不删,仅改标量
    default_hits = _dvids(mio.search(DENSE, SPARSE, topk=20))
    assert old_dvid not in default_hits and new_dvid in default_hits  # V4 主断言
    with_old = _dvids(mio.search(DENSE, SPARSE, topk=20, include_superseded=True))
    assert old_dvid in with_old


def test_finalize_is_replayable(revision_pair):
    pg, mio, ctx, old_dvid, new_dvid = revision_pair
    finalize.run(ctx, new_dvid)
    r2 = finalize.run(ctx, new_dvid)  # 重放
    assert r2.switched
    assert pg.get(DocVersion, old_dvid).version_status == "superseded"  # 终态不变
    mio.flush()
    assert old_dvid not in _dvids(mio.search(DENSE, SPARSE, topk=20))


def test_finalize_noop_without_supersedes(revision_pair):
    pg, mio, ctx, old_dvid, new_dvid = revision_pair
    result = finalize.run(ctx, old_dvid)  # 老版无 supersedes_version_id
    assert result.switched is False
    assert pg.get(DocVersion, old_dvid).version_status == "effective"  # 未被改动


# ── §1.1/§7.2:abolished(abolish_only 旧版终态)───────────────────
def test_finalize_abolishes_old_when_abolish_only(abolish_pair):
    pg, mio, ctx, old_dvid, new_dvid = abolish_pair
    result = finalize.run(ctx, new_dvid)
    assert result.switched and result.old_dvid == old_dvid

    # 旧版 + 其块 → abolished(非 superseded);新版仍 effective
    assert pg.get(DocVersion, old_dvid).version_status == "abolished"
    assert pg.get(DocVersion, old_dvid).version_status != "superseded"
    assert all(c.chunk_status == "abolished" for c in pg.get_chunks(old_dvid))
    assert pg.get(DocVersion, new_dvid).version_status == "effective"

    # Milvus:旧版未删、默认检索不见(abolished ∉ {effective, superseded});新版可见
    mio.flush()
    assert mio.count(old_dvid) == 1
    default_hits = _dvids(mio.search(DENSE, SPARSE, topk=20))
    assert old_dvid not in default_hits and new_dvid in default_hits


# ── §1.1/§7.2:upcoming(未来生效)+ 手动 activate ─────────────────
def test_finalize_defers_supersede_when_upcoming(upcoming_pair):
    pg, mio, ctx, old_dvid, new_dvid = upcoming_pair
    # 前置:新版 upcoming、其块默认检索不可见(status=upcoming ∉ {effective, superseded})
    assert pg.get(DocVersion, new_dvid).version_status == "upcoming"
    mio.flush()
    assert new_dvid not in _dvids(mio.search(DENSE, SPARSE, topk=20))

    result = finalize.run(ctx, new_dvid)  # upcoming → 不切换
    assert result.switched is False
    assert pg.get(DocVersion, old_dvid).version_status == "effective"  # 旧版保 effective
    assert all(c.chunk_status == "effective" for c in pg.get_chunks(old_dvid))
    # 旧版仍默认可见(未被替代),新版仍不可见
    mio.flush()
    default_hits = _dvids(mio.search(DENSE, SPARSE, topk=20))
    assert old_dvid in default_hits and new_dvid not in default_hits


def test_activate_flips_upcoming_then_supersedes(upcoming_pair):
    pg, mio, ctx, old_dvid, new_dvid = upcoming_pair
    finalize.run(ctx, new_dvid)  # upcoming 阶段:no switch(同上)

    # 手动 activate(对齐 CLI `demo activate`:PG 翻 effective → Milvus 从冷备重 upsert → finalize)
    pg.set_version_status(new_dvid, "effective")
    pg.set_chunk_status(new_dvid, "effective")
    mio.upsert(corpus_rows.rows_from_cold_strict(pg, new_dvid, "effective"))
    mio.flush()
    result = finalize.run(ctx, new_dvid)  # 现 effective → 触发延后的切换

    assert result.switched and result.old_dvid == old_dvid
    assert pg.get(DocVersion, new_dvid).version_status == "effective"
    assert pg.get(DocVersion, old_dvid).version_status == "superseded"  # 现已被替代
    mio.flush()
    default_hits = _dvids(mio.search(DENSE, SPARSE, topk=20))
    assert new_dvid in default_hits and old_dvid not in default_hits  # 新版上线、旧版退场


def test_live_status_matches_seed(upcoming_pair):
    """合成新版的 effective_date 确在未来 → live_status 判 upcoming(与 fixture 一致)。"""
    pg, mio, ctx, old_dvid, new_dvid = upcoming_pair
    dv = pg.get(DocVersion, new_dvid)
    assert live_status(dv.effective_date, datetime.date.today()) == "upcoming"
