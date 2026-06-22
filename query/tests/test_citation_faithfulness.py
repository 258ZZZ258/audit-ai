"""T11(单元):引用真实性代码级兜底 select_faithful + 无裸结论(stub 路径)。"""

from __future__ import annotations

from query.generate.citation_inject import build_citation_prompt
from query.generate.r1_evidence import select_faithful
from query.llm.stub import StubLLMClient


def test_select_faithful_drops_out_of_context():
    # 上下文外的 GHOST 被丢弃;去重保序
    assert select_faithful(["A", "GHOST", "B", "A"], ["A", "B", "C"]) == ["A", "B"]


def test_select_faithful_empty():
    assert select_faithful([], ["A"]) == []
    assert select_faithful(["A"], []) == []


def test_stub_answer_has_no_bare_conclusion():
    system, user = build_citation_prompt(
        "能否对外签合同", [{"clause_id": "X", "text": "第三条 合同应当经法务审查"}]
    )
    out = StubLLMClient().chat_json(system, user)
    assert "违规" not in out["answer"] and "合规" not in out["answer"]
    assert set(out["cited_clause_ids"]) <= {"X"}  # 引用真实性
