"""T1.3 ref_resolver R1–R3 纯规则:文档内指代 standoff 解析(§6.7)。

纯逻辑(无栈):验四类指代 R1 自指 / R2 相对 / R3 绝对 + 面包屑跳过 + 条头自指跳过。
R4 跨文档留 T2.4;款级「前款」chunk 级无款边界 → 保守标 unresolved 并计数。
"""

import pytest
from sqlalchemy import delete, select
from sqlalchemy import text as sqltext
from ulid import ULID

from common.pg_models import Chunk, ClauseReference, Document, DocVersion, ImportBatch
from pipeline.chunking.ref_resolver import resolve_refs, run_resolver
from pipeline.config import load_config
from pipeline.index.object_store import ObjectStore
from pipeline.index.pg_io import PgIO
from pipeline.stage_base import StageContext

DVID = "DV9"
NORMS = frozenset({"1", "2/15", "2/16", "3/21-1"})
ORDER = ["1", "2/15", "2/16", "3/21-1"]  # 条文档序(供 R2 前条)


def _find(refs, surface):
    return next(r for r in refs if r.surface_text == surface)


def test_r3_absolute_hit_skips_self_heading():
    # body 条头「第十六条」= 当前条(自指)跳过;引用「第十五条」命中 2/15
    refs = resolve_refs("第十六条 依照第十五条办理", 0, "2/16", NORMS, ORDER, DVID)
    surfaces = [r.surface_text for r in refs]
    assert "第十六条" not in surfaces  # 条头自指不产生 ref
    r = _find(refs, "第十五条")
    assert r.ref_type == "R3" and r.target_clause_path_norm == "2/15"
    assert r.resolution_status == "resolved" and r.target_doc_version_id == DVID


def test_r3_insert_article_hit():
    refs = resolve_refs("适用第二十一条之一", 0, "1", NORMS, ORDER, DVID)
    r = _find(refs, "第二十一条之一")
    assert r.ref_type == "R3" and r.target_clause_path_norm == "3/21-1"


def test_r3_out_of_range_unresolved():
    refs = resolve_refs("第九十九条", 0, "1", NORMS, ORDER, DVID)
    r = _find(refs, "第九十九条")
    assert r.ref_type == "R3" and r.resolution_status == "unresolved"
    assert r.target_clause_path_norm is None


def test_r1_doc_self():
    refs = resolve_refs("本办法所称费用", 0, "1", NORMS, ORDER, DVID)
    r = _find(refs, "本办法")
    assert r.ref_type == "R1" and r.target_doc_version_id == DVID
    assert r.target_clause_path_norm is None and r.resolution_status == "resolved"


def test_r1_ben_tiao():
    refs = resolve_refs("依本条规定", 0, "2/15", NORMS, ORDER, DVID)
    r = _find(refs, "本条")
    assert r.ref_type == "R1" and r.target_clause_path_norm == "2/15"


def test_r1_ben_zhang():
    refs = resolve_refs("本章另有规定", 0, "2/15", NORMS, ORDER, DVID)
    r = _find(refs, "本章")
    assert r.ref_type == "R1" and r.target_clause_path_norm == "2"  # 章 = path 首段


def test_r2_qian_tiao_hits_prev():
    refs = resolve_refs("依照前条规定", 0, "2/16", NORMS, ORDER, DVID)
    r = _find(refs, "前条")
    assert r.ref_type == "R2" and r.target_clause_path_norm == "2/15"
    assert r.resolution_status == "resolved"


def test_r2_qian_tiao_first_unresolved():
    refs = resolve_refs("前条", 0, "1", NORMS, ORDER, DVID)  # 首条无前条
    r = _find(refs, "前条")
    assert r.ref_type == "R2" and r.resolution_status == "unresolved"


def test_r2_qian_kuan_unresolved():
    refs = resolve_refs("前款所列情形", 0, "2/15", NORMS, ORDER, DVID)
    r = _find(refs, "前款")
    assert r.ref_type == "R2" and r.resolution_status == "unresolved"


def test_breadcrumb_skipped():
    text = "第一章 > 第三条\n依照第十五条"
    body_offset = text.index("\n") + 1
    refs = resolve_refs(text, body_offset, "3", NORMS, ORDER, DVID)
    assert [r.surface_text for r in refs] == ["第十五条"]  # 面包屑「第三条」被跳过
    assert all(r.span_start >= body_offset for r in refs)


# ── 集成:run_resolver 写 clause_references(连 PG;不可达 skip)──────────────
@pytest.fixture
def ref_stack():
    cfg = load_config()
    pg = PgIO.from_config(cfg)
    try:
        with pg.session() as s:
            s.execute(sqltext("select 1"))
    except Exception:
        pytest.skip("PG 不可达")
    bid, lid, dvid = "rr_" + str(ULID()), str(ULID()), str(ULID())
    with pg.session() as s:
        s.add(ImportBatch(batch_id=bid, source_dir="x"))
        s.add(Document(logical_id=lid, corpus_type="P-INT"))
        s.flush()
        s.add(
            DocVersion(
                doc_version_id=dvid,
                logical_id=lid,
                batch_id=bid,
                source_format="docx",
                source_hash="h" + dvid[:8],
                raw_object_key="k",
                pipeline_status="META_REVIEW",
            )
        )
        s.flush()
        # 第一条(引用第二条 → R3)、第二条(本办法 → R1);text = 面包屑 + "\n" + 正文
        s.add(
            Chunk(
                chunk_id=("rrA" + dvid)[:24],
                doc_version_id=dvid,
                clause_path="第一条",
                clause_path_norm="1/1",
                seq=0,
                breadcrumb="第一章 > 第一条",
                page_start=1,
                text="第一章 > 第一条\n第一条 依照第二条办理。",
                is_parent=False,
                is_table=False,
                chunk_status="effective",
            )
        )
        s.add(
            Chunk(
                chunk_id=("rrB" + dvid)[:24],
                doc_version_id=dvid,
                clause_path="第二条",
                clause_path_norm="1/2",
                seq=1,
                breadcrumb="第一章 > 第二条",
                page_start=1,
                text="第一章 > 第二条\n第二条 本办法另有规定的除外。",
                is_parent=False,
                is_table=False,
                chunk_status="effective",
            )
        )
    ctx = StageContext(config=cfg, object_store=ObjectStore.from_config(cfg), db=pg)
    yield pg, ctx, dvid
    with pg.session() as s:
        s.execute(delete(ClauseReference).where(ClauseReference.doc_version_id == dvid))
        s.execute(delete(Chunk).where(Chunk.doc_version_id == dvid))
        s.execute(delete(DocVersion).where(DocVersion.doc_version_id == dvid))
        s.execute(delete(Document).where(Document.logical_id == lid))
        s.execute(delete(ImportBatch).where(ImportBatch.batch_id == bid))


def _refs(pg, dvid):
    with pg.session() as s:
        return list(
            s.scalars(select(ClauseReference).where(ClauseReference.doc_version_id == dvid))
        )


def test_run_resolver_writes_clause_references(ref_stack):
    pg, ctx, dvid = ref_stack
    res = run_resolver(ctx, dvid)
    assert res.chunks == 2
    by_surface = {r.surface_text: r for r in _refs(pg, dvid)}
    # 第一条引用「第二条」→ R3 命中 1/2(条头「第一条」自指 + 面包屑「第一条」均跳)
    r3 = by_surface["第二条"]
    assert r3.ref_type == "R3" and r3.target_clause_path_norm == "1/2"
    assert r3.resolution_status == "resolved" and r3.method == "rule"
    assert "第一条" not in by_surface
    # 第二条「本办法」→ R1 文档自指
    assert by_surface["本办法"].ref_type == "R1"


def test_run_resolver_idempotent(ref_stack):
    pg, ctx, dvid = ref_stack
    run_resolver(ctx, dvid)
    first = len(_refs(pg, dvid))
    run_resolver(ctx, dvid)  # 内含 clear → 不翻倍
    assert len(_refs(pg, dvid)) == first
