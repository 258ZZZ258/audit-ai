"""D1 版本原子切换(finalize)集成测试(连 PG + Milvus;**免模型**——走 PG 冷备零重编码)。

不可达则 skip。seed 老/新两版(同 logical,新版 supersedes 老版),均以 effective 入库,跑 finalize:
验旧版 PG version_status/chunk_status + Milvus 标量均置 superseded(不删)、新版仍 effective、
默认检索不见旧版而 --include-superseded 可见、切换可重放幂等、无 supersedes 件 no-op。
"""

import pytest
from sqlalchemy import delete, text
from ulid import ULID

from pipeline.config import load_config
from pipeline.index import corpus_rows
from pipeline.index.milvus_io import MilvusIO, dense_to_bytes, sparse_to_bytes
from pipeline.index.object_store import ObjectStore
from pipeline.index.pg_io import PgIO
from pipeline.index.pg_models import Chunk, Document, DocVersion, ImportBatch, PipelineEvent
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


@pytest.fixture
def revision_pair(stack):
    """seed 同 logical 的老/新两版(均 INDEXED+effective,各 1 块带冷备),新版 supersedes 老版。"""
    pg, mio, ctx = stack
    bid, lid = "as_" + str(ULID()), str(ULID())
    old_dvid, new_dvid = str(ULID()), str(ULID())

    def _seed_version(dvid: str, *, tag: str, supersedes: str | None) -> None:
        with pg.session() as s:
            s.add(
                DocVersion(
                    doc_version_id=dvid, logical_id=lid, batch_id=bid, source_format="docx",
                    source_hash="h" + dvid[:8], raw_object_key="k",
                    pipeline_status=PS.INDEXED.value, version_status="effective",
                    perm_tag="内部", biz_domain="DISCLOSURE", issuer="CSRC",
                    supersedes_version_id=supersedes,
                    version_relation="revise_replace" if supersedes else None,
                )
            )
            s.flush()
            # 同毫秒 ULID 仅末位不同 → 用 tag 前缀保证两版 chunk_id 不撞(devlog ULID 截断坑)
            s.add(
                Chunk(
                    chunk_id=(tag + dvid)[:24], doc_version_id=dvid, text="第一条 内容。",
                    clause_path="第一章/第一条", clause_path_norm="1/1", seq=1, page_start=1,
                    is_parent=False, is_table=False, chunk_status="effective",
                    dense_vec_cold=dense_to_bytes(DENSE), sparse_vec_cold=sparse_to_bytes(SPARSE),
                )
            )
        mio.upsert(corpus_rows.rows_from_cold(pg, dvid, "effective"))  # 模拟已索引 effective

    with pg.session() as s:
        s.add(ImportBatch(batch_id=bid, source_dir="x"))
        s.add(Document(logical_id=lid, corpus_type="P-INT", title="信息披露办法"))
    _seed_version(old_dvid, tag="o", supersedes=None)
    _seed_version(new_dvid, tag="n", supersedes=old_dvid)
    mio.flush()

    yield pg, mio, ctx, old_dvid, new_dvid
    for d in (old_dvid, new_dvid):
        mio.delete(d)
    mio.flush()
    with pg.session() as s:
        for d in (old_dvid, new_dvid):
            s.execute(delete(Chunk).where(Chunk.doc_version_id == d))
            s.execute(delete(PipelineEvent).where(PipelineEvent.doc_version_id == d))
            s.execute(delete(DocVersion).where(DocVersion.doc_version_id == d))
        s.execute(delete(Document).where(Document.logical_id == lid))
        s.execute(delete(ImportBatch).where(ImportBatch.batch_id == bid))


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
