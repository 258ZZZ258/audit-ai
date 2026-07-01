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
        seq=1, doc_id="D1", doc_version_id="V1", title="《客户适当性管理实施细则》",
        match_score=0.92, clause_excerpt="第三章 适还比例界定…",
    ).to_dict()
    assert d["seq"] == 1 and d["title"].startswith("《")
    assert d["match_score"] == 0.92 and d["clause_excerpt"]
    # doc_no/publish_date/effective_date/issuing_dept/version/status 为 None → 省略
    for k in ("doc_no", "publish_date", "effective_date", "issuing_dept", "version", "status"):
        assert k not in d


def test_regulation_hit_optional_included_when_set():
    d = RegulationHit(
        seq=2, doc_id="D2", doc_version_id="V2", title="t", match_score=0.95,
        clause_excerpt="x", doc_no="NEEQ-QF-2020-034", publish_date="2021-02-01",
        effective_date="2022-02-15", issuing_dept="合规管理部", status="effective",
    ).to_dict()
    assert d["doc_no"] == "NEEQ-QF-2020-034"
    assert d["publish_date"] == "2021-02-01" and d["effective_date"] == "2022-02-15"
    assert d["issuing_dept"] == "合规管理部" and d["status"] == "effective"


def test_clause_hit_theme_summary_omitted_when_absent():
    d = ClauseHit(
        seq=1, clause_id="c1", clause_title="第六条 客户适当性管理要求",
        doc_title="《证券登记业务管理办法》", doc_id="D1", match_score=0.98,
    ).to_dict()
    assert d["clause_id"] == "c1" and d["match_score"] == 0.98
    for k in ("clause_path", "summary", "theme"):
        assert k not in d  # ⚠-data/⚠-model 缺省省略


def test_regulatory_rule_hit_related_internal_omitted_when_empty():
    d = RegulatoryRuleHit(
        seq=1, clause_id="c9", doc_id="D9", title="《证券期货投资者适当性管理办法》",
        core_requirement="证券公司应当了解客户…",
    ).to_dict()
    assert "related_internal" not in d  # 空列表(clause_references 未落)→ 省略
    d2 = RegulatoryRuleHit(
        seq=1, clause_id="c9", doc_id="D9", title="t", core_requirement="r",
        related_internal=["《客户适当性管理制度》"], issuing_body="中国证监会",
    ).to_dict()
    assert d2["related_internal"] == ["《客户适当性管理制度》"]
    assert d2["issuing_body"] == "中国证监会"


def test_case_hit_l2_and_llm_fields_omitted_when_absent():
    d = CaseHit(
        seq=1, case_id="V3", doc_version_id="V3",
        title="某商业银行理财子公司未有效评估客户风险等级案",
        regulator="上海证监局", penalty_date="2024-10-17",
    ).to_dict()
    assert d["regulator"] == "上海证监局" and d["penalty_date"] == "2024-10-17"
    for k in ("violation_theme", "related_regulations", "core_issue", "insight"):
        assert k not in d  # L2 / LLM 字段缺失 → 省略(零臆造)


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
        regulations=TabPayload(items=[RegulationHit(1, "D", "V", "t", 0.9, "x")]),
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
