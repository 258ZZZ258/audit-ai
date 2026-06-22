"""R1 依据查询主路径(充分路径):引用 ID 注入生成 + 四级锚点回查 → §10 契约。

充分性自检与拒答(覆盖感知)由 graph 编排;本模块负责**充分时**的生成,并对 LLM 输出做不可信兜底。
红线:
- 引用真实性:``select_faithful`` 代码级兜底——答案只能引用上下文 clause_id;
- **LLM 输出不可信**:无忠实引用 → **绝不出 evidence 裸答**,降级覆盖拒答(security LLM05;SPEC SC1);
- **degraded 块不参与条款级引用**(CLAUDE.md 硬约束)——不进生成上下文 / 不作引用;
- 无裸结论:prompt 约束 §7.1 +(§9.2 多模型复核本切片未实装)。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from query.contract import AnswerBlock, BlockType, Citation, QueryResult, RouteType
from query.generate.anchors import fetch_anchors, fetch_texts
from query.generate.citation_inject import build_citation_prompt
from query.refuse.coverage_refusal import refuse_coverage

_CLOSEST_N = 3  # 无忠实引用降级拒答时,附最接近 N 条供人工核实

# 裸结论判定词:LLM 答复(不可信边界)含之 → 按潜在裸结论处理。
# ⚠ 钝兜底,宁过滤勿漏(保留引用、替中性文案);precise 版是 §9.2 多模型复核(本切片未实装)。
_BARE_CONCLUSION = ("违规", "违法", "合规", "合法")
_NEUTRAL_ANSWER = "根据检索到的现行制度条款,相关依据见所引条款原文(详见引用);具体认定请人工判断。"


def select_faithful(cited_ids: Iterable[str], allowed_ids: Iterable[str]) -> list[str]:
    """只保留出现在上下文(allowed)里的引用 id(去重保序)——引用真实性的代码级兜底。"""
    allowed = set(allowed_ids)
    out: list[str] = []
    for cid in cited_ids:
        if cid in allowed and cid not in out:
            out.append(cid)
    return out


def sanitize_answer(answer: str) -> str:
    """LLM 答复含裸结论词 → 替为中性文案(保留引用),守"无裸结论"红线(LLM 输出不可信)。"""
    return _NEUTRAL_ANSWER if any(t in answer for t in _BARE_CONCLUSION) else answer


def generate_evidence(
    query: str, candidates: Sequence, pg, llm, *, exhausted_scope: Sequence[str] = ()
) -> QueryResult:
    """``candidates``: 检索候选(``retrieve.Candidate``)。

    充分时生成带四级引用的答复;**无忠实引用则降级覆盖拒答**(返回 ``route_type=refuse``),
    ``exhausted_scope`` 供拒答可解释。degraded 候选不进上下文、不作引用(CLAUDE.md 契约)。
    """
    # 契约:degraded 块仅全文检索、不参与条款级引用 → 排除出生成上下文与引用
    clause_cands = [c for c in candidates if not c.degraded]
    ids = [c.chunk_id for c in clause_cands]
    texts = fetch_texts(pg, ids)
    blocks = [
        {"clause_id": c.chunk_id, "text": texts[c.chunk_id], "clause_path": c.clause_path}
        for c in clause_cands
        if texts.get(c.chunk_id)
    ]
    out = llm.chat_json(*build_citation_prompt(query, blocks))
    cited = select_faithful(out.get("cited_clause_ids", []), [b["clause_id"] for b in blocks])
    anchors = fetch_anchors(pg, cited)
    citations: list[Citation] = [anchors[c] for c in cited if c in anchors]
    # LLM 输出按不可信处理:无忠实引用 → 绝不出 evidence 裸答,降级覆盖拒答(附最接近 N 条)
    if not citations:
        closest = list(fetch_anchors(pg, ids[:_CLOSEST_N]).values())
        return refuse_coverage(exhausted_scope, closest)
    # LLM 答复文本按不可信处理:含裸结论词 → 替中性文案(保留真实引用),守红线
    answer = sanitize_answer(str(out.get("answer", "")))
    return QueryResult(
        route_type=RouteType.EVIDENCE,
        answer_blocks=[AnswerBlock(BlockType.TEXT, answer)],
        citations=citations,
        confidence=0.7,  # ⚠ Q8 待标定:置信度口径占位(有引用方达此路径)
    )
