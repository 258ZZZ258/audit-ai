"""T1.3 ref_resolver R1–R3 纯规则:文档内指代 standoff 解析(§6.7)。

纯逻辑(无栈):验四类指代 R1 自指 / R2 相对 / R3 绝对 + 面包屑跳过 + 条头自指跳过。
R4 跨文档留 T2.4;款级「前款」chunk 级无款边界 → 保守标 unresolved 并计数。
"""

import pytest
from sqlalchemy import delete, select
from sqlalchemy import text as sqltext
from ulid import ULID

from common.pg_models import Chunk, ClauseReference, DictAlias, Document, DocVersion, ImportBatch
from pipeline.chunking.ref_resolver import (
    PgXRefLookup,
    XRefCandidate,
    XRefHit,
    align_xref,
    extract_xrefs,
    resolve_refs,
    run_resolver,
)
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
                chunk_type="clause",
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
                chunk_type="clause",
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


def test_run_resolver_skips_non_clause_chunks(ref_stack):
    # P-CASE/P-QA 块(chunk_type != clause)不解析:案例「第X条」是引用外规(走 case_ref_align),非自指
    pg, ctx, dvid = ref_stack
    with pg.session() as s:
        rows = list(s.scalars(select(Chunk).where(Chunk.doc_version_id == dvid)))
        rows[0].chunk_type = "case_section"  # 模拟 P-CASE 块
        cid = rows[0].chunk_id
    res = run_resolver(ctx, dvid)
    assert res.chunks == 1  # 2 块中 1 个改 case_section → 仅剩 1 个 clause 块
    assert all(r.chunk_id != cid for r in _refs(pg, dvid))  # case_section 块不产 ref


# ── R4 跨文档:extract_xrefs 纯函数提取(无栈,T1)────────────────────────────
def _xc(cands, title):
    return next(c for c in cands if c.title == title)


def test_extract_with_doc_number():
    cands = extract_xrefs("依照《证券法》（主席令〔2014〕12号）第一百九十三条办理", 0)
    c = _xc(cands, "证券法")
    assert c.doc_number is not None and "〔2014〕" in c.doc_number
    assert c.clause_raw == "第一百九十三条"
    assert isinstance(c, XRefCandidate)


def test_extract_without_doc_number():
    c = _xc(extract_xrefs("《证券法》第一百九十六条规定", 0), "证券法")
    assert c.doc_number is None and c.clause_raw == "第一百九十六条"


def test_extract_document_level_no_clause():
    # 只引文档不引条 → 文档级候选(clause_raw=None)
    c = _xc(extract_xrefs("参照《公司法》的有关规定", 0), "公司法")
    assert c.clause_raw is None


def test_extract_multiple_refs():
    cands = extract_xrefs("《证券法》第一条与《公司法》第二条", 0)
    assert {c.title for c in cands} == {"证券法", "公司法"}
    assert _xc(cands, "证券法").clause_raw == "第一条"
    assert _xc(cands, "公司法").clause_raw == "第二条"


def test_extract_insert_article():
    c = _xc(extract_xrefs("《交易办法》第二十一条之一", 0), "交易办法")
    assert c.clause_raw == "第二十一条之一"


def test_extract_arabic_clause():
    assert _xc(extract_xrefs("《证券法》第196条", 0), "证券法").clause_raw == "第196条"


def test_extract_skips_breadcrumb():
    text = "《某规则》第一章 > 第三条\n依照《证券法》第十条"
    body_offset = text.index("\n") + 1
    cands = extract_xrefs(text, body_offset)
    assert [c.title for c in cands] == ["证券法"]  # 面包屑里的《某规则》跳过
    assert all(c.span_start >= body_offset for c in cands)


def test_extract_no_book_title_no_candidate():
    assert extract_xrefs("本办法依据有关法律制定", 0) == []


# ── R4 跨文档:align_xref 四态(注入 fake lookup,无栈,T2)─────────────────────
class _FakeLookup:
    def __init__(self, hit):
        self._hit = hit

    def resolve(self, doc_number, title):
        return self._hit


def _cand(clause_raw):
    return XRefCandidate("证券法", None, clause_raw, 3, 12, f"《证券法》{clause_raw or ''}")


def test_align_resolved_clause_hit():
    hit = XRefHit("single", "DVEXT", "X号", frozenset({"2/15", "2/16"}))
    pr = align_xref(_cand("第十五条"), _FakeLookup(hit))
    assert pr.ref_type == "R4" and pr.resolution_status == "resolved"
    assert pr.target_doc_version_id == "DVEXT" and pr.target_clause_path_norm == "2/15"


def test_align_resolved_document_level():
    hit = XRefHit("single", "DVEXT", "X号", frozenset({"2/15"}))
    pr = align_xref(_cand(None), _FakeLookup(hit))  # 只引文档不引条
    assert pr.resolution_status == "resolved" and pr.target_clause_path_norm is None
    assert pr.target_doc_version_id == "DVEXT"


def test_align_ambiguous():
    pr = align_xref(_cand("第十五条"), _FakeLookup(XRefHit("multiple", None, None, frozenset())))
    assert pr.resolution_status == "ambiguous"
    assert pr.target_doc_version_id is None and pr.target_clause_path_norm is None


def test_align_pending_target():
    pr = align_xref(_cand("第十五条"), _FakeLookup(XRefHit("none", None, None, frozenset())))
    assert pr.resolution_status == "pending_target" and pr.target_doc_version_id is None


def test_align_unresolved_out_of_range():
    hit = XRefHit("single", "DVEXT", "X号", frozenset({"2/15"}))
    pr = align_xref(_cand("第九十九条"), _FakeLookup(hit))  # 条号超界
    assert pr.resolution_status == "unresolved"
    assert pr.target_doc_version_id == "DVEXT" and pr.target_clause_path_norm is None


def test_align_unresolved_unparseable_clause():
    hit = XRefHit("single", "DVEXT", "X号", frozenset({"15"}))
    pr = align_xref(_cand("第X条"), _FakeLookup(hit))  # 条号无法归一(非中文/数字)
    assert pr.resolution_status == "unresolved" and pr.target_clause_path_norm is None


# ── R4 跨文档:PgXRefLookup 三级查(连 PG,栈未起 skip,T3)─────────────────────
@pytest.fixture
def xref_stack():
    cfg = load_config()
    pg = PgIO.from_config(cfg)
    try:
        with pg.session() as s:
            s.execute(sqltext("select 1"))
    except Exception:
        pytest.skip("PG 不可达")
    bid = "xr_" + str(ULID())
    lid_ext, dv_ext = str(ULID()), str(ULID())
    lid_self, dv_self = str(ULID()), str(ULID())
    title = "测试证券法_" + dv_ext[:8]  # 唯一后缀:不限 corpus 全库查,避免撞真实 effective doc
    num = "测试令〔2020〕" + dv_ext[:6] + "号"
    alias = "测试简称_" + dv_ext[:8]
    with pg.session() as s:
        s.add(ImportBatch(batch_id=bid, source_dir="x"))
        s.add(Document(logical_id=lid_ext, corpus_type="P-EXT"))
        s.add(Document(logical_id=lid_self, corpus_type="P-INT"))
        s.flush()
        s.add(DocVersion(doc_version_id=dv_ext, logical_id=lid_ext, batch_id=bid,
            source_format="docx", source_hash="h" + dv_ext[:8], raw_object_key="k",
            pipeline_status="INDEXED", version_status="effective", title=title, doc_number=num))
        s.add(DocVersion(doc_version_id=dv_self, logical_id=lid_self, batch_id=bid,
            source_format="docx", source_hash="h" + dv_self[:8], raw_object_key="k",
            pipeline_status="INDEXED", version_status="effective", title="自身内规"))
        s.flush()
        for i, cpn in enumerate(["2/15", "2/16"]):
            s.add(Chunk(chunk_id=(f"xc{i}" + dv_ext)[:24], doc_version_id=dv_ext,
                clause_path="x", clause_path_norm=cpn, seq=i, page_start=1, text="t",
                is_parent=False, is_table=False, chunk_type="clause", chunk_status="effective"))
        s.add(DictAlias(alias=alias, canonical_doc_number=None, canonical_title=title,
            dict_version="test"))
    yield pg, dv_ext, dv_self, title, num, alias
    with pg.session() as s:
        s.execute(delete(Chunk).where(Chunk.doc_version_id.in_([dv_ext, dv_self])))
        s.execute(delete(DocVersion).where(DocVersion.doc_version_id.in_([dv_ext, dv_self])))
        s.execute(delete(Document).where(Document.logical_id.in_([lid_ext, lid_self])))
        s.execute(delete(DictAlias).where(DictAlias.alias == alias))
        s.execute(delete(ImportBatch).where(ImportBatch.batch_id == bid))


def test_pglookup_by_number(xref_stack):
    pg, dv_ext, dv_self, title, num, alias = xref_stack
    hit = PgXRefLookup(pg, dv_self).resolve(num, None)
    assert hit.status == "single" and hit.doc_version_id == dv_ext
    assert "2/15" in hit.clause_norms


def test_pglookup_by_title(xref_stack):
    pg, dv_ext, dv_self, title, num, alias = xref_stack
    hit = PgXRefLookup(pg, dv_self).resolve(None, title)
    assert hit.status == "single" and hit.doc_version_id == dv_ext


def test_pglookup_by_alias_title_fallback(xref_stack):
    pg, dv_ext, dv_self, title, num, alias = xref_stack
    hit = PgXRefLookup(pg, dv_self).resolve(None, alias)  # 别名→canonical_title→命中
    assert hit.status == "single" and hit.doc_version_id == dv_ext


def test_pglookup_excludes_self(xref_stack):
    pg, dv_ext, dv_self, title, num, alias = xref_stack
    hit = PgXRefLookup(pg, dv_ext).resolve(None, title)  # 从目标自身视角 → 排除 self
    assert hit.status == "none"


def test_pglookup_none(xref_stack):
    pg, dv_ext, dv_self, title, num, alias = xref_stack
    assert PgXRefLookup(pg, dv_self).resolve(None, "绝不存在标题_ZZZ").status == "none"


def test_pglookup_multiple_ambiguous(xref_stack):
    pg, dv_ext, dv_self, title, num, alias = xref_stack
    lid2, dv2, bid2 = str(ULID()), str(ULID()), "xr2_" + str(ULID())
    with pg.session() as s:
        s.add(ImportBatch(batch_id=bid2, source_dir="x"))
        s.add(Document(logical_id=lid2, corpus_type="P-INT"))
        s.flush()
        s.add(DocVersion(doc_version_id=dv2, logical_id=lid2, batch_id=bid2,
            source_format="docx", source_hash="h" + dv2[:8], raw_object_key="k",
            pipeline_status="INDEXED", version_status="effective", title=title))
    try:
        hit = PgXRefLookup(pg, dv_self).resolve(None, title)  # 两 doc 同 title → multiple
        assert hit.status == "multiple" and hit.doc_version_id is None
    finally:
        with pg.session() as s:
            s.execute(delete(DocVersion).where(DocVersion.doc_version_id == dv2))
            s.execute(delete(Document).where(Document.logical_id == lid2))
            s.execute(delete(ImportBatch).where(ImportBatch.batch_id == bid2))


# ── R4 跨文档:run_resolver 集成(连 PG,栈未起 skip,T4)──────────────────────
def _ctx(pg):
    cfg = load_config()
    return StageContext(config=cfg, object_store=ObjectStore.from_config(cfg), db=pg)


def _add_self_clause(pg, dv_self, body):
    with pg.session() as s:
        s.add(
            Chunk(
                chunk_id=("rs" + dv_self)[:24],
                doc_version_id=dv_self,
                clause_path="第一条",
                clause_path_norm="1",
                seq=0,
                breadcrumb="第一章 > 第一条",
                page_start=1,
                text=f"第一章 > 第一条\n{body}",
                is_parent=False,
                is_table=False,
                chunk_type="clause",
                chunk_status="effective",
            )
        )


def _r4_refs(pg, dvid):
    with pg.session() as s:
        return list(
            s.scalars(
                select(ClauseReference).where(
                    ClauseReference.doc_version_id == dvid,
                    ClauseReference.ref_type == "R4",
                )
            )
        )


def test_run_resolver_writes_r4_resolved(xref_stack):
    pg, dv_ext, dv_self, title, num, alias = xref_stack
    _add_self_clause(pg, dv_self, f"依照《{title}》第十五条办理。")
    run_resolver(_ctx(pg), dv_self)
    r4 = _r4_refs(pg, dv_self)
    assert len(r4) == 1 and r4[0].resolution_status == "resolved"
    assert r4[0].target_doc_version_id == dv_ext and r4[0].target_clause_path_norm == "2/15"
    assert r4[0].method == "rule"
    # 「第十五条」属 R4 跨文档(《title》第十五条),不重复写文档内 R3
    with pg.session() as s:
        r3 = list(
            s.scalars(
                select(ClauseReference).where(
                    ClauseReference.doc_version_id == dv_self,
                    ClauseReference.ref_type == "R3",
                )
            )
        )
    assert all("第十五条" not in x.surface_text for x in r3)


def test_run_resolver_r4_pending_target(xref_stack):
    pg, dv_ext, dv_self, title, num, alias = xref_stack
    _add_self_clause(pg, dv_self, "依照《绝不在库的某法ZZZ》第一条。")
    run_resolver(_ctx(pg), dv_self)
    r4 = _r4_refs(pg, dv_self)
    assert len(r4) == 1 and r4[0].resolution_status == "pending_target"
    assert r4[0].target_doc_version_id is None


def test_run_resolver_r4_idempotent(xref_stack):
    pg, dv_ext, dv_self, title, num, alias = xref_stack
    _add_self_clause(pg, dv_self, f"依照《{title}》第十五条。")
    run_resolver(_ctx(pg), dv_self)
    run_resolver(_ctx(pg), dv_self)  # clear_refs 内含 → R4 不翻倍
    assert len(_r4_refs(pg, dv_self)) == 1
