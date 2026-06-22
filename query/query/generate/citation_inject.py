"""§7.1 引用 ID 注入式生成:上下文每块注入 ``[[clause_id:X]]`` 标记 + prompt 强约束。

LLM **只做选择不做生成**——只能引用上下文中带 clause_id 的内容,禁凭记忆造发文字号/条号,
不出"违规/合规"裸结论(R1)。标记格式与 ``query.llm.stub`` 解析约定一致。
"""

from __future__ import annotations

_SYSTEM = (
    "你是制度查询助手。只能依据下方提供的、带 [[clause_id:...]] 标记的条款内容作答;"
    "引用时必须标注对应 clause_id。禁止凭记忆生成发文字号、条号或任何未在上下文出现的依据,"
    "不得给出'违规/合规'等裸结论。若上下文不足以支持回答,如实说明、不要编造。"
    '以 JSON 返回 {"answer": 文字, "cited_clause_ids": [clause_id 列表]}。'
)


def _marker(clause_id: str) -> str:
    return f"[[clause_id:{clause_id}]]"


def build_citation_prompt(query: str, blocks: list[dict]) -> tuple[str, str]:
    """``blocks``: ``[{clause_id, text, clause_path?}]``。返回 ``(system, user)``。"""
    lines = [
        f"{_marker(b['clause_id'])} {b.get('clause_path') or ''} {b.get('text', '')}".strip()
        for b in blocks
    ]
    ctx = "\n".join(lines) if lines else "(无候选条款)"
    user = f"问题:{query}\n\n候选条款:\n{ctx}"
    return _SYSTEM, user
