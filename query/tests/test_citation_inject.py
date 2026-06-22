"""T10:引用 ID 注入 prompt 构造 + 与 stub 解析约定闭环。"""

from __future__ import annotations

from query.generate.citation_inject import build_citation_prompt
from query.llm.stub import StubLLMClient


def test_prompt_injects_clause_id_markers_and_constraints():
    system, user = build_citation_prompt(
        "报销规定?",
        [
            {"clause_id": "AAA", "text": "第一条 ...", "clause_path": "第一章第一条"},
            {"clause_id": "BBB", "text": "第二条 ...", "clause_path": "第一章第二条"},
        ],
    )
    assert "[[clause_id:AAA]]" in user and "[[clause_id:BBB]]" in user
    assert "报销规定?" in user
    # 系统约束:只引用上下文 / 禁编造 / 不裸结论
    assert "只能依据" in system and "禁止凭记忆" in system and "裸结论" in system


def test_stub_roundtrip_selects_only_context_ids():
    blocks = [{"clause_id": "X", "text": "t1"}, {"clause_id": "Y", "text": "t2"}]
    system, user = build_citation_prompt("q", blocks)
    out = StubLLMClient().chat_json(system, user)
    assert set(out["cited_clause_ids"]) <= {"X", "Y"}  # 注入↔解析闭环


def test_empty_blocks_render_placeholder():
    _system, user = build_citation_prompt("q", [])
    assert "(无候选条款)" in user
