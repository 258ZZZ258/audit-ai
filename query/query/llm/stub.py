"""零网络确定性 LLM 桩:从 user prompt 的 ``[[clause_id:X]]`` 标记选前 N 个 clause_id 回填。

作用:让引用 ID 注入(§7.1)**可被测**——输出的 ``cited_clause_ids`` 必 ⊆ 上下文注入集合
(零编造)。引用注入的标记格式由 ``generate/citation_inject``(T10)产出,本桩按同一约定解析。

输出 schema(R1 主路径约定,见 ``generate/r1_evidence``):
    ``{"answer": str, "cited_clause_ids": list[str]}``
``answer`` 为**中性模板**,绝不含"违规/合规"裸结论(守红线)。
"""

from __future__ import annotations

import re

#: 引用注入标记(与 citation_inject 约定一致):``[[clause_id:<id>]]``
_MARKER = re.compile(r"\[\[clause_id:([^\]]+)\]\]")


class StubLLMClient:
    """默认后端。``max_citations`` 限制回填条数(去重保序)。"""

    def __init__(self, max_citations: int = 3) -> None:
        self._max = max_citations

    def chat_json(self, system: str, user: str) -> dict:
        seen: list[str] = []
        for cid in _MARKER.findall(user):
            if cid not in seen:
                seen.append(cid)
        picked = seen[: self._max]
        answer = (
            "根据检索到的现行制度条款,相关依据见所引条款原文(详见引用)。"
            if picked
            else "未在检索上下文中找到带依据标识的条款。"
        )
        return {"answer": answer, "cited_clause_ids": picked}
