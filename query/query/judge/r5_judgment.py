"""R5 判定型编排(§6.5):桥接入口 ∥ 混合检索 → 三段式硬约束 → §9.2 复核。**默认零-LLM。**

红线:`route_type=judgmental` + `review_required=true`,三段式**无 verdict 槽**;条款逐字命中四级锚点
(PG 权威);**绝不出违规/合规裸结论**(形态 + `framing.strip_bare_conclusion` + §9.2 复核接口)。
桥接入口 **consumed-when-present**:`cited_regulations` 默认空 → 反查 `[]` → 降级 hybrid-only。
模块级零 pipeline 导入(retriever/pg/llm 经形参注入;degraded 就地 inline)。
"""

from __future__ import annotations

from sqlalchemy import select

from common.pg_models import Case, Chunk, DocVersion
from query.case.bridge import _norm, _norm_dn
from query.contract import QueryResult, RouteType
from query.generate.anchors import fetch_anchors, fetch_texts
from query.judge.framing import build_framing
from query.judge.review import review_tentative
from query.llm import maybe_make_llm_client
from query.refuse.coverage_refusal import refuse_coverage

#: 覆盖拒答 exhausted_scope 兜底(判定型;必非空,可解释)。
_FALLBACK_SCOPE = ["现行制度(行为合规判断)"]


def _norm_doc_no(s: str | None) -> str:
    """文号归一(复用 bridge 口径:半角 + 去空白 + 括号变体)。"""
    return _norm_dn(_norm(s or ""))


def _entry_doc_clause(entry) -> tuple[str, str] | None:
    """``cited_regulations`` 单条目 → (归一文号, 归一条款路径);非 dict / 缺键 → None。"""
    if not isinstance(entry, dict):
        return None
    doc_no = entry.get("doc_no") or entry.get("文号")
    clause = entry.get("clause_path") or entry.get("clause_path_norm") or entry.get("条款")
    if not (doc_no and clause):
        return None
    return _norm_doc_no(doc_no), _norm(clause)


def resolve_cited_clauses(pg, case_dvids) -> list[str]:
    """桥接入口(§6.3 反查):案例 ``cited_regulations`` → 外规条款 chunk_id(effective + 非 degraded)。

    **consumed-when-present**:默认空 → ``[]``(降级 hybrid-only,绝不臆造外规)。
    """
    dvids = list(dict.fromkeys(case_dvids))
    if not dvids:
        return []
    out: list[str] = []
    with pg.session() as s:
        entries: list[tuple[str, str]] = []
        for dvid in dvids:
            case = s.get(Case, dvid)
            for e in (getattr(case, "cited_regulations", None) or []) if case else []:
                key = _entry_doc_clause(e)
                if key:
                    entries.append(key)
        if not entries:
            return []  # 默认空路径(L2 关)
        # 文号 → effective doc_version_id(归一匹配)
        dn_map: dict[str, str] = {}
        for d in s.scalars(select(DocVersion).where(DocVersion.version_status == "effective")):
            if d.doc_number:
                dn_map.setdefault(_norm_doc_no(d.doc_number), d.doc_version_id)
        for norm_dn_key, norm_clause in entries:
            target = dn_map.get(norm_dn_key)
            if target is None:
                continue
            chunk = s.scalars(
                select(Chunk).where(
                    Chunk.doc_version_id == target,
                    Chunk.clause_path_norm == norm_clause,
                    Chunk.degraded.isnot(True),  # degraded 不参与条款级引用(契约)
                )
            ).first()
            if chunk and chunk.chunk_id not in out:
                out.append(chunk.chunk_id)
    return out


def answer_judgment(query, retriever, pg, llm, qcfg) -> QueryResult:
    """§6.5:桥接入口 ∪ hybrid → 三段式(① 依据条款 ② 框定 ③ 标识)+ review_required。空→覆盖拒答。"""
    # ① 桥接入口(consumed-when-present)+ ② hybrid(内规+外规);degraded 就地剔除(契约)
    case_dvids = [c.doc_version_id for c in retriever.retrieve_cases(query) if c.doc_version_id]
    bridge_ids = resolve_cited_clauses(pg, case_dvids)
    hybrid_ids = [c.chunk_id for c in retriever.retrieve(query) if not c.degraded]
    ids = list(dict.fromkeys([*bridge_ids, *hybrid_ids]))[: qcfg.topk]  # 桥接优先,截 topk

    scope = list(_FALLBACK_SCOPE)
    if not ids:
        return refuse_coverage(scope, [])
    anchors = fetch_anchors(pg, ids)
    citations = [anchors[i] for i in ids if i in anchors]
    if not citations:  # 候选回查 PG 全缺锚点 → 不出空 judgmental,覆盖拒答(红线:锚点 PG 权威)
        return refuse_coverage(scope, [])

    texts = fetch_texts(pg, ids)
    clauses = [
        {"doc_title": anchors[i].doc_title, "clause_path": anchors[i].clause_path,
         "text": texts.get(i, "")}
        for i in ids if i in anchors
    ]
    blocks = build_framing(clauses, query, llm, qcfg)          # ② 框定 + ③ 标识(无 verdict 槽)
    # §9.2 复核:开+gateway+有 key → 用独立 review_model(Kimi)建复核客户端,与主答(Qwen)分离(§9.1);
    # 关/stub/无 key → maybe_make_llm_client 返 None → `or llm` 直通主答(零网络、不崩溃,同款
    # OFFLINE-GATE)。喂 clauses(含条文原文)而非 citations(仅锚点):忠实性须对条文原文校验
    # (R5-REVIEW-NEEDS-CLAUSE-EVIDENCE)。
    review_llm = maybe_make_llm_client(
        qcfg.judge_multimodel_review, qcfg, model=qcfg.review_model
    ) or llm
    blocks = review_tentative(blocks, clauses, review_llm, qcfg)
    return QueryResult(
        route_type=RouteType.JUDGMENTAL,
        answer_blocks=blocks,
        citations=citations,
        review_required=True,      # 前端差异化渲染人工复核框(§6.5③)
        confidence=0.5,            # ⚠ 占位,不参与任何闸门
    )
