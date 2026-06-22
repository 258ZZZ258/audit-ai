"""T12:覆盖感知拒答(§8.2)+ 兜底拒答(§6.8)——话术 / exhausted_scope / 最接近 N 条 / 无裸结论。"""

from __future__ import annotations

from query.contract import Citation, RouteType
from query.refuse.coverage_refusal import refuse_coverage, refuse_out_of_domain


def test_coverage_refusal_shape():
    r = refuse_coverage(["投顾业务"], [Citation(clause_id="A"), Citation(clause_id="B")])
    assert r.route_type is RouteType.REFUSE
    assert r.exhausted_scope == ["投顾业务"]
    text = r.answer_blocks[0].content
    assert "投顾业务" in text
    assert "未检索到" in text and "明确禁止性规定" in text  # §8.2 话术
    assert "2 条最接近" in text
    assert [c.clause_id for c in r.citations] == ["A", "B"]


def test_coverage_refusal_caps_closest():
    cits = [Citation(clause_id=str(i)) for i in range(10)]
    r = refuse_coverage(["X"], cits, max_closest=3)
    assert len(r.citations) == 3
    assert "3 条最接近" in r.answer_blocks[0].content


def test_coverage_refusal_no_closest_omits_list():
    r = refuse_coverage(["投顾业务"], [])
    assert "最接近" not in r.answer_blocks[0].content
    assert r.citations == []
    assert "未检索到" in r.answer_blocks[0].content  # 仍可解释


def test_coverage_refusal_empty_scope_fallback():
    r = refuse_coverage([], [])
    assert "相关业务" in r.answer_blocks[0].content
    assert r.exhausted_scope == []


def test_out_of_domain_refusal():
    r = refuse_out_of_domain()
    assert r.route_type is RouteType.REFUSE
    assert "超出" in r.answer_blocks[0].content and "能力范围" in r.answer_blocks[0].content
    assert r.exhausted_scope == [] and r.citations == []


def test_refusal_never_bare_conclusion():
    for r in (refuse_coverage(["X"], []), refuse_out_of_domain()):
        text = r.answer_blocks[0].content
        assert "违规" not in text and "合规" not in text
