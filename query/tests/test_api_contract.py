"""T1(SPEC-API §4/§5):结构化四-Tab 契约 dataclass + QueryResult 加法 structured/meta。

红线:**§10 byte 等价** —— 默认 QueryResult 的 to_dict 仍恰为既有 8 键
(structured=None、meta={} 时缺省省略),CLI `query ask` 输出不变。
命中项可选字段缺失即省略(零臆造,承 CaseCard 先例)。
"""

from __future__ import annotations

import json

from query.contract import (
    BlockType,
    CaseHit,
    ClauseHit,
    DigestCard,
    QueryResult,
    RegulationHit,
    RegulatoryRuleHit,
    RouteType,
    StructuredResult,
    TabPayload,
)

# ── §10 byte 等价:加法后默认输出仍恰 8 键 ────────────────────────────────────
_BASE_KEYS = {
    "route_type", "answer_blocks", "citations", "confidence",
    "ai_label", "review_required", "exhausted_scope", "export_enabled",
}


def test_default_to_dict_byte_equivalent_no_structured_meta():
    d = QueryResult(route_type=RouteType.EVIDENCE).to_dict()
    assert set(d) == _BASE_KEYS  # structured/meta 缺省不出现 → 与既有契约 byte 等价


def test_structured_and_meta_appear_only_when_populated():
    empty = _empty_structured()
    r = QueryResult(route_type=RouteType.EVIDENCE, structured=empty, meta={"elapsed_ms": 2300})
    d = r.to_dict()
    assert d["structured"]["regulations"] == {"total": 0, "items": []}
    assert d["meta"] == {"elapsed_ms": 2300}
    # 加法不动既有键
    assert _BASE_KEYS <= set(d)


# ── 命中项序列化 + 可选字段缺省省略 ──────────────────────────────────────────
def test_regulation_hit_required_present_optional_omitted():
    d = RegulationHit(
        seq=1, file_name="《客户适当性管理实施细则》",
    ).to_dict()
    assert d == {"seq": 1, "file_name": "《客户适当性管理实施细则》"}
    for k in (
        "title", "doc_id", "doc_version_id", "match_score", "clause_excerpt", "doc_no",
        "publish_date", "issuing_dept", "version", "status", "display_fields",
    ):
        assert k not in d


def test_regulation_hit_optional_included_when_set():
    d = RegulationHit(
        seq=2, file_name="制度", document_number="NEEQ-QF-2020-034",
        effective_date="2022-02-15", issuing_department="合规管理部",
        validity_status="effective", business_category=["经纪业务"], tags=["客户"],
    ).to_dict()
    assert d["document_number"] == "NEEQ-QF-2020-034"
    assert d["effective_date"] == "2022-02-15"
    assert d["issuing_department"] == "合规管理部"
    assert d["validity_status"] == "effective"
    assert d["business_category"] == ["经纪业务"] and d["tags"] == ["客户"]


def test_clause_hit_theme_summary_omitted_when_absent():
    d = ClauseHit(
        seq=1, clause_id="c1", clause_title="第六条 客户适当性管理要求",
        doc_title="《证券登记业务管理办法》", doc_id="D1", match_score=0.98,
    ).to_dict()
    assert d["clause_id"] == "c1" and d["match_score"] == 0.98
    for k in ("clause_path", "summary", "theme"):
        assert k not in d  # ⚠-data/⚠-model 缺省省略


def test_regulatory_rule_hit_only_real_kb_fields():
    d = RegulatoryRuleHit(
        seq=1, file_name="《证券期货投资者适当性管理办法》",
    ).to_dict()
    assert d == {"seq": 1, "file_name": "《证券期货投资者适当性管理办法》"}
    d2 = RegulatoryRuleHit(
        seq=1, file_name="t", document_number="证监会令第130号", issuing_unit="中国证监会",
        issue_date="2023-05-01", validity_status="effective", legal_hierarchy="部门规章",
        tags=["适当性管理"], applicable_objects=["证券公司"],
    ).to_dict()
    assert d2["document_number"] == "证监会令第130号"
    assert d2["issuing_unit"] == "中国证监会"
    assert d2["applicable_objects"] == ["证券公司"]
    for k in ("title", "doc_no", "issuing_body", "core_requirement", "related_internal"):
        assert k not in d2


def test_case_hit_only_real_kb_fields():
    d = CaseHit(
        case_name="某商业银行理财子公司未有效评估客户风险等级案",
        issuing_unit="上海证监局", issue_date="2024-10-17",
    ).to_dict()
    assert d["case_name"].startswith("某商业银行")
    assert d["issuing_unit"] == "上海证监局" and d["issue_date"] == "2024-10-17"
    for k in (
        "seq", "case_id", "doc_version_id", "title", "regulator", "penalty_date",
        "violation_theme", "related_regulations", "core_issue", "insight", "display_fields",
    ):
        assert k not in d


def test_digest_card_and_tab_payload_shapes():
    card = DigestCard(tag="盾", title="客户适当性评估", body="应充分了解客户…").to_dict()
    assert card == {"tag": "盾", "title": "客户适当性评估", "body": "应充分了解客户…"}
    # TabPayload total 缺省 = len(items)
    tab = TabPayload(items=[DigestCard("盾", "a", "b")]).to_dict()
    assert tab["total"] == 1 and tab["items"][0]["title"] == "a"
    tab2 = TabPayload(items=[], total=3).to_dict()  # total 可显式(截断/分页时 ≠ len)
    assert tab2 == {"total": 3, "items": []}


def test_structured_result_full_shape_and_json_roundtrip():
    s = StructuredResult(
        regulations=TabPayload(items=[RegulationHit(1, "t")]),
        clauses=TabPayload(items=[]),
        regulatory_rules=TabPayload(items=[]),
        cases=TabPayload(items=[]),
        citation_advice=["建议引用《证券公司境外服务管理规定》第十八条"],
        regulatory_digest=[DigestCard("查", "持续管理要求", "应定期评估")],
        case_insights=[],
    )
    r = QueryResult(route_type=RouteType.EVIDENCE, structured=s, meta={"total_hits": 1})
    d = json.loads(r.to_json())
    assert set(d["structured"]) == {
        "regulations", "clauses", "regulatory_rules", "cases",
        "citation_advice", "regulatory_digest", "case_insights",
    }
    assert d["structured"]["regulations"]["total"] == 1
    assert d["structured"]["citation_advice"][0].startswith("建议引用")
    assert d["structured"]["regulatory_digest"][0]["tag"] == "查"
    assert d["meta"]["total_hits"] == 1
    # 答复正文块仍走既有 answer_blocks 契约(不被 structured 取代)
    assert d["route_type"] == "evidence" and BlockType.TEXT.value == "text"


def _empty_structured() -> StructuredResult:
    return StructuredResult(
        regulations=TabPayload(items=[]), clauses=TabPayload(items=[]),
        regulatory_rules=TabPayload(items=[]), cases=TabPayload(items=[]),
    )
