"""T8:八路路由 golden(R1/R7/R8 实装、R2–R6 诚实打标)+ R7/R8 触发 + 置信度。"""

from __future__ import annotations

import json
from pathlib import Path

from query.contract import RouteType
from query.understand.classify import classify
from query.understand.router import route

_GOLDEN = Path(__file__).parent / "golden" / "router_golden.jsonl"


def _load_golden() -> list[dict]:
    return [
        json.loads(line)
        for line in _GOLDEN.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_router_golden():
    for item in _load_golden():
        got = route(item["query"], classify(item["query"])).route_type
        assert got == RouteType(item["route"]), (
            f"{item['query']}: 期望 {item['route']} 实得 {got}"
        )


def test_all_eight_routes_covered():
    routes = {RouteType(i["route"]) for i in _load_golden()}
    # 八路全实装(R5 收官):R1–R8 均有真实 route_type 落点,无占位
    assert {RouteType.EVIDENCE, RouteType.CLARIFY, RouteType.REFUSE} <= routes
    assert {
        RouteType.CHANGE, RouteType.CASE, RouteType.ENUMERATE,
        RouteType.JUDGMENTAL, RouteType.STATISTICAL,
    } <= routes


def test_enumerate_listing_routes_to_enumerate():
    # §6.4 列举型「哪些制度…/列出所有…」→ ENUMERATE,不串 R1 依据(R4 实装回归)
    for q in ("哪些制度规定了客户身份识别", "列出所有关于反洗钱的要求", "有哪些规定涉及适当性管理"):
        assert route(q, classify(q)).route_type is RouteType.ENUMERATE, q


def test_list_statistical_routes_to_statistical():
    # §6.6 列表型统计「X年以来…处罚有哪些」→ STATISTICAL(此前误落 evidence/R1,Codex R6-ROUTING)
    for q in ("2024年以来的处罚有哪些", "2024年以来期货监管处罚有哪些"):
        assert route(q, classify(q)).route_type is RouteType.STATISTICAL, q


def test_off_domain_refuses():
    assert route("今天天气怎么样", classify("今天天气怎么样")).route_type is RouteType.REFUSE


def test_domain_anchor_blocks_false_refuse():
    # 含领域锚点(股票+处罚)不应误判跑题
    q = "操纵股票被处罚的案例有哪些依据"
    assert route(q, classify(q)).route_type is not RouteType.REFUSE


def test_ambiguous_clarifies():
    assert route("它呢", classify("它呢")).route_type is RouteType.CLARIFY


def test_explicit_confidence_ge_evidence_default():
    ev = route("印章保管由谁负责", classify("印章保管由谁负责"))
    jg = route("这是否违规", classify("这是否违规"))
    assert ev.route_type is RouteType.EVIDENCE
    assert jg.confidence >= ev.confidence  # 显式判定关键词置信度更高
