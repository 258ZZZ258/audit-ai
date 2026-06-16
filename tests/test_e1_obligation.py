"""A1 · E1 义务打标:`match_obligation` 单元(免栈)+ `tag`/`clear` 集成(连 PG,免模型)。"""

import pytest
from sqlalchemy import delete, select, text
from ulid import ULID

from pipeline.config import ObligationConfig, load_config
from pipeline.enrich import e1_obligation as e1
from pipeline.index.object_store import ObjectStore
from pipeline.index.pg_io import PgIO
from pipeline.index.pg_models import Chunk, ClauseTag, Document, DocVersion, ImportBatch
from pipeline.stage_base import StageContext

# ── 单元:match_obligation(免栈,真实 obligation.yaml 词表)──────────────
CFG = load_config().obligation


@pytest.mark.parametrize(
    "s,expect,ev",
    [
        ("第二条 有关部门应当在二十四小时内书面报告", True, "应当"),
        ("印章由专人保管,保管人不得擅自用印", True, "不得"),
        ("报销人应如实填写报销单", True, "应"),  # bare 应(句首,前缀不在排除表)
        ("公司应披露重大事项", True, "应"),  # 应+动词=义务,evidence 退化为 应
        ("公司对相应债权未提取足额坏账准备", False, None),  # 相应 排除,无其他义务词
        ("适应市场变化调整经营策略", False, None),  # 适应 排除
        ("对应当事人作出相应处理", False, None),  # 对应当:前缀排除作用于 应当 marker
        ("履行相应程序后报本所", False, None),  # 相应程序:相 前缀排除
        ("本办法自发布之日起施行", False, None),  # 施行日期句:负例
        ("本办法所称重大事项,是指下列情形", False, None),  # 释义句:负例
        ("", False, None),
    ],
)
def test_match_obligation(s, expect, ev):
    ok, e = e1.match_obligation(s, CFG)
    assert ok is expect
    if expect:
        assert e == ev


def test_prefix_exclusion_applies_to_marker():
    # bare_ying 关时,应当 marker 仍受前缀排除:对应当事人 不误命中,门应当报告 命中
    cfg = ObligationConfig(
        markers=["应当"], bare_ying=False, exclusions=["对应"], accuracy_threshold=0.9
    )
    assert e1.match_obligation("对应当事人作出处理", cfg) == (False, None)
    assert e1.match_obligation("有关部门应当报告", cfg)[0] is True


def test_marker_priority():
    ok, e = e1.match_obligation("必须并且不得擅自处理", CFG)  # 多义务词:返 markers 顺序首个
    assert ok and e in CFG.markers


def test_bare_ying_toggle():
    cfg = ObligationConfig(markers=["不得"], bare_ying=False, exclusions=[], accuracy_threshold=0.9)
    assert e1.match_obligation("报销人应如实填写", cfg) == (False, None)  # bare_ying 关:单应不算
    assert e1.match_obligation("不得擅自", cfg)[0] is True


# ── 集成:tag / clear(连 PG,免模型)────────────────────────────
@pytest.fixture
def pg_ctx():
    cfg = load_config()
    pg = PgIO.from_config(cfg)
    try:
        with pg.session() as s:
            s.execute(text("select 1"))
    except Exception:
        pytest.skip("PG 不可达")
    yield pg, StageContext(config=cfg, object_store=ObjectStore.from_config(cfg), db=pg)


@pytest.fixture
def seeded(pg_ctx):
    pg, ctx = pg_ctx
    bid, lid, dvid = "e1_" + str(ULID()), str(ULID()), str(ULID())
    # (文本, is_parent):3 义务非 parent + 1 非义务 + 1 parent(义务文本但 parent 不打标)
    specs = [
        ("应当报告", False),
        ("不得擅自", False),
        ("应如实填写", False),
        ("本办法自发布之日起施行", False),
        ("第一章 总则 应当遵守", True),
    ]
    with pg.session() as s:
        s.add(ImportBatch(batch_id=bid, source_dir="x"))
        s.add(Document(logical_id=lid, corpus_type="P-INT"))
        s.flush()
        s.add(
            DocVersion(
                doc_version_id=dvid, logical_id=lid, batch_id=bid, source_format="docx",
                source_hash="h" + dvid[:8], raw_object_key="k", pipeline_status="META_REVIEW",
                perm_tag="内部", biz_domain="X", issuer="CSRC",
            )
        )
        s.flush()
        for i, (txt, parent) in enumerate(specs):
            s.add(
                Chunk(
                    chunk_id=(f"e{i}" + dvid)[:24], doc_version_id=dvid, text=txt,
                    clause_path=str(i), clause_path_norm=str(i), seq=i, page_start=1,
                    is_parent=parent, is_table=False, chunk_status="effective",
                )
            )
    yield pg, ctx, dvid
    with pg.session() as s:
        ids = list(s.scalars(select(Chunk.chunk_id).where(Chunk.doc_version_id == dvid)))
        if ids:
            s.execute(delete(ClauseTag).where(ClauseTag.chunk_id.in_(ids)))
        s.execute(delete(Chunk).where(Chunk.doc_version_id == dvid))
        s.execute(delete(DocVersion).where(DocVersion.doc_version_id == dvid))
        s.execute(delete(Document).where(Document.logical_id == lid))
        s.execute(delete(ImportBatch).where(ImportBatch.batch_id == bid))


def _tags(pg, dvid):
    with pg.session() as s:
        ids = list(s.scalars(select(Chunk.chunk_id).where(Chunk.doc_version_id == dvid)))
        return list(
            s.scalars(
                select(ClauseTag).where(
                    ClauseTag.chunk_id.in_(ids), ClauseTag.tag_type == "is_obligation"
                )
            )
        )


def test_tag_writes_only_obligation_nonparent(seeded):
    pg, ctx, dvid = seeded
    r = e1.tag(ctx, dvid)
    assert r.total == 4  # 非 parent 块(parent 不计)
    assert r.tagged == 3  # 应当报告 / 不得擅自 / 应如实填写;施行日期句不中;parent 不打
    tags = _tags(pg, dvid)
    assert len(tags) == 3
    assert all(t.tag_value == "true" and t.evidence for t in tags)


def test_clear_then_tag_idempotent(seeded):
    pg, ctx, dvid = seeded
    e1.tag(ctx, dvid)
    first = {t.chunk_id for t in _tags(pg, dvid)}
    n = e1.clear(ctx, dvid)
    assert n == 3 and not _tags(pg, dvid)  # clear 删净
    e1.tag(ctx, dvid)
    assert {t.chunk_id for t in _tags(pg, dvid)} == first  # 重打同集 → 幂等
