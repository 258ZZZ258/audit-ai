"""审查修复回归(findings 1–3,单元):degraded 不参与条款引用 / 无忠实引用降级拒答 / scope 非空。"""

from __future__ import annotations

from query.contract import RouteType
from query.generate.r1_evidence import generate_evidence, sanitize_answer
from query.graph import resolve_scope
from query.llm.stub import StubLLMClient
from query.retrieve.hybrid import Candidate, drop_degraded


def _cand(chunk_id: str, *, degraded: bool) -> Candidate:
    return Candidate(chunk_id, 1.0, "P-INT", "dv", "第一条", 1, degraded, "hybrid")


# ── finding 1:degraded 块不参与条款级引用 ──────────────────────────────
def test_drop_degraded_filters():
    cands = [_cand("a", degraded=False), _cand("b", degraded=True)]
    assert [c.chunk_id for c in drop_degraded(cands)] == ["a"]


def test_generate_evidence_degraded_only_refuses():
    # 仅有 degraded 候选 → 排除后无上下文 → 不出 evidence/不引用 degraded → 降级拒答
    res = generate_evidence(
        "q", [_cand("a", degraded=True)], pg=None, llm=StubLLMClient(), exhausted_scope=["X"]
    )
    assert res.route_type is RouteType.REFUSE
    assert res.citations == []


# ── finding 2:LLM 无忠实引用 → 不出 evidence 裸答,降级拒答 ──────────────
def test_generate_evidence_no_candidates_refuses_with_scope():
    res = generate_evidence("q", [], pg=None, llm=StubLLMClient(), exhausted_scope=["投顾业务"])
    assert res.route_type is RouteType.REFUSE
    assert res.exhausted_scope == ["投顾业务"]
    assert res.citations == []


# ── finding 3:覆盖拒答 exhausted_scope 必非空 ──────────────────────────
def test_resolve_scope_uses_matters_dedup():
    assert resolve_scope(["投顾业务", "投顾业务"]) == ["投顾业务"]


def test_resolve_scope_fallback_nonempty():
    assert resolve_scope([]) != []  # 未识别事项时确定性兜底,保可解释


# ── 复审 finding:LLM 答复(不可信)含裸结论 → 代码级后检替中性 ──────────
def test_sanitize_answer_strips_bare_conclusion():
    for verdict in ("该行为违规", "属于合规操作", "构成违法", "完全合法"):
        assert "违规" not in sanitize_answer(verdict)
        assert "违法" not in sanitize_answer(verdict)
        assert "合规" not in sanitize_answer(verdict)
        assert "合法" not in sanitize_answer(verdict)


def test_sanitize_answer_keeps_clean_text():
    clean = "依据第三条,合同应当经法务审查并由授权人签署。"
    assert sanitize_answer(clean) == clean
