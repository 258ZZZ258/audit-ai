"""R1 依据查询主路径(充分路径):引用 ID 注入生成 + 四级锚点回查 → §10 契约。

充分性自检与拒答分别在 ``sufficiency`` / ``refuse``(由 graph 编排);本模块只负责**充分时**的生成。
红线:引用真实性(``select_faithful`` 代码级兜底——答案只能引用上下文 clause_id)、无裸结论
(prompt 约束 §7.1 + §9.2 多模型复核,后者本切片未实装)。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from query.contract import AnswerBlock, BlockType, Citation, QueryResult, RouteType
from query.generate.anchors import fetch_anchors, fetch_texts
from query.generate.citation_inject import build_citation_prompt


def select_faithful(cited_ids: Iterable[str], allowed_ids: Iterable[str]) -> list[str]:
    """只保留出现在上下文(allowed)里的引用 id(去重保序)——引用真实性的代码级兜底。"""
    allowed = set(allowed_ids)
    out: list[str] = []
    for cid in cited_ids:
        if cid in allowed and cid not in out:
            out.append(cid)
    return out


def generate_evidence(query: str, candidates: Sequence, pg, llm) -> QueryResult:
    """``candidates``: 含 ``.chunk_id`` / ``.clause_path`` 的检索候选(``retrieve.Candidate``)。"""
    ids = [c.chunk_id for c in candidates]
    texts = fetch_texts(pg, ids)
    blocks = [
        {"clause_id": c.chunk_id, "text": texts[c.chunk_id], "clause_path": c.clause_path}
        for c in candidates
        if texts.get(c.chunk_id)
    ]
    system, user = build_citation_prompt(query, blocks)
    out = llm.chat_json(system, user)
    cited = select_faithful(out.get("cited_clause_ids", []), [b["clause_id"] for b in blocks])
    anchors = fetch_anchors(pg, cited)
    citations: list[Citation] = [anchors[c] for c in cited if c in anchors]
    answer = str(out.get("answer", ""))
    return QueryResult(
        route_type=RouteType.EVIDENCE,
        answer_blocks=[AnswerBlock(BlockType.TEXT, answer)],
        citations=citations,
        confidence=0.7 if citations else 0.0,  # ⚠ Q8 待标定:置信度口径占位
    )
