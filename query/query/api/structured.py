"""T2(SPEC-API §4):结构化四-Tab 结果装配。

两层:``assemble_structured``(**纯函数**,吃候选 + 预取 PG 数据 → ``StructuredResult``,无栈可测)
+ ``fetch_pg_context``(PG 权威回查,集成测)。装配在 **API 边界层**,不进 graph 域节点。

分区:``retrieve()`` 候选按 ``corpus_type`` 分内规(P-INT)/外规(P-EXT);案例走 ``retrieve_cases()``
(P-CASE)。匹配度 = 候选集内融合分 min-max 归一 → 0–1(前端直显 %)。⚠-data(theme/关联内规/违规
主题/关联制度)缺失即省略;⚠-model(摘要走截断兜底、core_issue/insight/卡片/引用建议)LLM 默认关 →
缺省 None/[]。案例要素逐字来自 PG ``cases``(零臆造,承 ``case_card.CaseCard``)。
"""

from __future__ import annotations

from sqlalchemy import select

from common.pg_models import Case, Chunk, DocVersion
from query.contract import (
    CaseHit,
    ClauseHit,
    RegulationHit,
    RegulatoryRuleHit,
    StructuredResult,
    TabPayload,
)

_INT = "P-INT"   # corpus_type:内规
_EXT = "P-EXT"   # corpus_type:外规
_EXCERPT_LEN = 140   # 制度节选 / 核心监管要求 截断长度(⚠ 可调)
_SUMMARY_LEN = 100   # 条款摘要截断长度(⚠-model 兜底,⚠ 可调)


# ── 纯函数装配(无栈可测)────────────────────────────────────────────────────
def assemble_structured(cands, case_cands, chunk_doc, case_rows) -> StructuredResult:
    """候选 + 预取 PG 数据 → 四-Tab。

    ``cands``/``case_cands``:``retrieve()``/``retrieve_cases()`` 候选(已 drop_degraded、按分降序)。
    ``chunk_doc``:``{chunk_id: (chunk, doc_version)}``;
    ``case_rows``:``{doc_version_id: (case, doc_version)}``。
    """
    internal = [c for c in cands if c.corpus_type == _INT]
    external = [c for c in cands if c.corpus_type == _EXT]
    norm = _normalizer([c.score for c in cands])
    norm_case = _normalizer([c.score for c in case_cands])
    return StructuredResult(
        regulations=TabPayload(items=_regulations(internal, chunk_doc, norm)),
        clauses=TabPayload(items=_clauses(internal, chunk_doc, norm)),
        regulatory_rules=TabPayload(items=_reg_rules(external, chunk_doc)),
        cases=TabPayload(items=_cases(case_cands, case_rows, norm_case)),
        # ⚠-model 卡片/引用建议:LLM 提炼开关默认关 → 空(StructuredResult 默认 [],前端隐藏)
    )


def _clauses(cands, chunk_doc, norm) -> list[ClauseHit]:
    """命中条款:逐候选一行(chunk 级),按分降序。"""
    out: list[ClauseHit] = []
    for c in cands:
        chunk, dv = chunk_doc.get(c.chunk_id, (None, None))
        if chunk is None:
            continue
        out.append(ClauseHit(
            seq=len(out) + 1, clause_id=c.chunk_id,
            clause_title=_clause_title(chunk.clause_path), doc_title=_title(dv),
            doc_id=chunk.doc_version_id, match_score=norm(c.score),
            clause_path=chunk.clause_path, summary=_truncate(chunk.text, _SUMMARY_LEN),
            # theme(⚠-data):无 clause_tags 回查 → None(省略);后续迭代接打标
        ))
    return out


def _regulations(cands, chunk_doc, norm) -> list[RegulationHit]:
    """命中制度:按 doc_version_id 去重(保最高分块作节选),按分降序。"""
    out: list[RegulationHit] = []
    for seq, (c, chunk, dv) in enumerate(_dedup_by_doc(cands, chunk_doc), 1):
        out.append(RegulationHit(
            seq=seq, doc_id=chunk.doc_version_id, doc_version_id=chunk.doc_version_id,
            title=_title(dv), match_score=norm(c.score),
            clause_excerpt=_truncate(chunk.text, _EXCERPT_LEN),
            doc_no=_attr(dv, "doc_number"), publish_date=_iso(_attr(dv, "issue_date")),
            effective_date=_iso(_attr(dv, "effective_date")), issuing_dept=_attr(dv, "issuer"),
            version=_iso(_attr(dv, "issue_date")), status=_attr(dv, "version_status"),
        ))
    return out


def _reg_rules(cands, chunk_doc) -> list[RegulatoryRuleHit]:
    """监管规则(外规):按 doc_version_id 去重,核心监管要求取最高分块节选。

    **无匹配度列**(原型 监管规则 tab 无「匹配度」)→ 不带 match_score。
    """
    out: list[RegulatoryRuleHit] = []
    for seq, (c, chunk, dv) in enumerate(_dedup_by_doc(cands, chunk_doc), 1):
        out.append(RegulatoryRuleHit(
            seq=seq, clause_id=c.chunk_id, doc_id=chunk.doc_version_id, title=_title(dv),
            core_requirement=_truncate(chunk.text, _EXCERPT_LEN),
            issuing_body=_attr(dv, "issuer"), doc_no=_attr(dv, "doc_number"),
            publish_date=_iso(_attr(dv, "issue_date")),
            # related_internal(⚠-data):clause_references 未落 → 空(省略);theme 同
        ))
    return out


def _cases(cands, case_rows, norm) -> list[CaseHit]:
    """相关案例:按 doc_version_id 去重(一案一卡),要素逐字来自 PG ``cases``。"""
    best: dict = {}
    for c in cands:
        dvid = c.doc_version_id
        if not dvid:
            continue
        cur = best.get(dvid)
        if cur is None or c.score > cur.score:
            best[dvid] = c
    out: list[CaseHit] = []
    ranked = sorted(best.items(), key=lambda kv: kv[1].score, reverse=True)
    for seq, (dvid, _c) in enumerate(ranked, 1):
        case, dv = case_rows.get(dvid, (None, None))
        out.append(CaseHit(
            seq=seq, case_id=dvid, doc_version_id=dvid, title=_title(dv),
            regulator=_attr(case, "penalty_org"), penalty_date=_iso(_attr(case, "penalty_date")),
            violation_theme=_attr(case, "violation_category"),   # L2:缺→省略
            related_regulations=list(_attr(case, "cited_regulations") or []),  # L2:缺→省略
            # core_issue/insight(⚠-model):LLM 关 → None(省略)
        ))
    return out


# ── PG 权威回查(集成测)──────────────────────────────────────────────────────
def fetch_pg_context(pg, cands, case_cands):
    """回查 ``retrieve``/``retrieve_cases`` 候选所需 PG 数据 → ``(chunk_doc, case_rows)``。

    ``pg`` = ``pipeline.index.pg_io.PgIO``(``.session()``)。权威表回查,非 Milvus 截断。
    """
    chunk_doc = {}
    ids = list(dict.fromkeys(c.chunk_id for c in cands))
    if ids:
        with pg.session() as s:
            chunks = _index(s, select(Chunk).where(Chunk.chunk_id.in_(ids)), "chunk_id")
            dvids = {c.doc_version_id for c in chunks.values()}
            dvs = _by_dvid(s, dvids)
        for cid in ids:
            ch = chunks.get(cid)
            chunk_doc[cid] = (ch, dvs.get(ch.doc_version_id) if ch else None)
    case_rows = {}
    case_dvids = list(dict.fromkeys(c.doc_version_id for c in case_cands if c.doc_version_id))
    if case_dvids:
        with pg.session() as s:
            case_stmt = select(Case).where(Case.doc_version_id.in_(case_dvids))
            cases = _index(s, case_stmt, "doc_version_id")
            dvs = _by_dvid(s, case_dvids)
        for dvid in case_dvids:
            case_rows[dvid] = (cases.get(dvid), dvs.get(dvid))
    return chunk_doc, case_rows


def _index(s, stmt, key) -> dict:
    """执行 ``stmt`` → ``{getattr(row, key): row}``。"""
    return {getattr(r, key): r for r in s.scalars(stmt)}


def _by_dvid(s, dvids) -> dict:
    """按 ``doc_version_id`` 集合批量回查 ``DocVersion``;空集 → ``{}``。"""
    if not dvids:
        return {}
    stmt = select(DocVersion).where(DocVersion.doc_version_id.in_(list(dvids)))
    return _index(s, stmt, "doc_version_id")


# ── 小工具 ───────────────────────────────────────────────────────────────────
def _dedup_by_doc(cands, chunk_doc):
    """按 ``doc_version_id`` 去重(保最高分候选)→ 按分降序的 ``(cand, chunk, dv)`` 列表。"""
    best: dict[str, tuple] = {}
    for c in cands:
        chunk, dv = chunk_doc.get(c.chunk_id, (None, None))
        if chunk is None:
            continue
        dvid = chunk.doc_version_id
        cur = best.get(dvid)
        if cur is None or c.score > cur[0].score:
            best[dvid] = (c, chunk, dv)
    return sorted(best.values(), key=lambda t: t[0].score, reverse=True)


def _normalizer(scores):
    """候选集内 min-max 归一 → [0,1]。空 → 0.0;单点/等值 → 1.0。"""
    if not scores:
        return lambda _s: 0.0
    lo, hi = min(scores), max(scores)
    if hi <= lo:
        return lambda _s: 1.0
    span = hi - lo
    return lambda s: round((s - lo) / span, 4)


def _clause_title(clause_path) -> str:
    """条款名称 = clause_path 末段(如「第三章/第三条 适还比例」→「第三条 适还比例」)。"""
    if not clause_path:
        return ""
    return clause_path.split("/")[-1].strip()


def _truncate(text, n) -> str:
    if not text:
        return ""
    t = text.strip()
    return t if len(t) <= n else t[:n].rstrip() + "…"


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else None


def _attr(obj, name):
    return getattr(obj, name, None) if obj is not None else None


def _title(dv) -> str:
    return _attr(dv, "title") or ""
