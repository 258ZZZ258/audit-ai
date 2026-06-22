"""T2:§10 输出契约全字段 + 序列化形状;QueryState 字段齐全(可拓展性根基)。"""

from __future__ import annotations

import json

from query.contract import AnswerBlock, BlockType, Citation, QueryResult, RouteType
from query.state import QueryState


def test_query_result_to_dict_has_all_contract_keys():
    d = QueryResult(route_type=RouteType.EVIDENCE).to_dict()
    assert set(d) == {
        "route_type", "answer_blocks", "citations", "confidence",
        "ai_label", "review_required", "exhausted_scope", "export_enabled",
    }
    assert d["route_type"] == "evidence"
    assert d["ai_label"] is True and d["export_enabled"] is True
    assert d["review_required"] is False
    assert d["answer_blocks"] == [] and d["citations"] == [] and d["exhausted_scope"] == []
    assert d["confidence"] == 0.0


def test_citation_four_level_anchor_fields():
    d = Citation(
        clause_id="abc", doc_title="t", doc_no="No.1", clause_path="第三章第二十一条",
        page_start=7, page_end=7, version="v1", status="effective",
    ).to_dict()
    # 四级:clause_id → 文档(标题/文号/版本) → 条款路径 → 页码 → 状态
    assert set(d) == {
        "clause_id", "doc_title", "doc_no", "clause_path",
        "page_start", "page_end", "version", "status",
    }
    assert d["clause_id"] == "abc" and d["page_start"] == 7 and d["status"] == "effective"


def test_answer_block_shape_and_stream_default():
    assert AnswerBlock(type=BlockType.TEXT, content="x").to_dict() == {
        "type": "text", "content": "x", "stream": True
    }


def test_query_result_json_roundtrip():
    r = QueryResult(
        route_type=RouteType.REFUSE,
        exhausted_scope=["投顾业务"],
        answer_blocks=[AnswerBlock(BlockType.TEXT, "未检索到对该行为的明确禁止性规定")],
        citations=[Citation(clause_id="c1")],
    )
    d = json.loads(r.to_json())
    assert d["route_type"] == "refuse"
    assert d["exhausted_scope"] == ["投顾业务"]
    assert d["answer_blocks"][0]["type"] == "text"
    assert d["citations"][0]["clause_id"] == "c1"


def test_query_state_carries_full_design_fields():
    s = QueryState(query="q")
    # §2.5-2 全字段在场 —— 加节点永不改状态契约
    for fld in (
        "query", "history", "rewrites", "scene", "route_type",
        "candidates", "exhausted_scope", "citations", "review", "answer_blocks",
    ):
        assert hasattr(s, fld)
    assert s.query == "q" and s.history == [] and s.route_type is None
