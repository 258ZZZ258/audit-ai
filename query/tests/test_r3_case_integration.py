"""T4(集成):R3 端到端连真栈——P-CASE 处罚决定书 → 案例卡片(PG 权威)+ 精确反查(手插 refs)。

gate:PIPELINE_EMBEDDING_MODEL + PG + Milvus + soffice(``case_stack`` fixture)。未满足即 skip。
红线:卡片要素逐字来自 PG ``cases``/``doc_versions``(非 Milvus 截断 / 非 LLM);L2 默认空 → 省略不臆造;
``cited_regulations`` 空时精确反查无数据(默认),手插后机制可命中(真实 JSONB 读)。
"""

from __future__ import annotations

import json

import pytest

from common.pg_models import Case
from query.case.bridge import cases_for_clauses, norm_ref
from query.case.r3_case import answer_case
from query.config import load_query_config
from query.contract import BlockType, RouteType
from query.retrieve.hybrid import Retriever


@pytest.fixture(autouse=True)
def _ensure_milvus_connected(case_stack):
    """重连 Milvus(幂等):pymilvus 全局 "default" 连接被 test_r2 模块级 stack teardown 的
    ``mio.disconnect()`` 断开;本文件按字母序在 r2 之后跑,检索前须重连,否则 ConnectionNotExist。
    """
    case_stack.mio.connect()


def _answer(case_stack):
    retr = Retriever(case_stack.ctx.embedding, case_stack.mio, load_query_config())
    return answer_case(case_stack.case_query, retr, case_stack.pg, load_query_config())


def _cards(res):
    return [json.loads(b.content) for b in res.answer_blocks if b.type is BlockType.CASE_CARD]


def _card_for(res, dvid):
    return next((c for c in _cards(res) if c["doc_version_id"] == dvid), None)


def test_r3_case_route_returns_card(case_stack):
    res = _answer(case_stack)
    assert res.route_type is RouteType.CASE
    card = _card_for(res, case_stack.case_dvid)
    assert card is not None, "案例卡片应含 ingest 的案例件"
    # 要素逐字 PG 权威(penalty_org 取 body 抬头「北京证监局」,非 manifest issuer)
    assert card["penalty_org"] == "北京证监局"
    assert card["respondent"] == "某某证券有限公司"
    assert card["penalty_date"] == "2024-03-15"
    assert "罚款" in card["penalty_type"]
    assert card["title"] == "北京证监局行政处罚决定书"   # doc_versions 权威标题
    # L2 字段默认空 → 省略(零臆造)
    assert "cited_regulations" not in card
    assert "violation_category" not in card


def test_r3_one_card_per_case(case_stack):
    # 同案多 chunk(case_summary + case_section)命中 → 去重一案一卡
    dvids = [c["doc_version_id"] for c in _cards(_answer(case_stack))]
    assert dvids.count(case_stack.case_dvid) == 1


def test_precise_reverse_lookup_real_pg(case_stack):
    pg, dvid = case_stack.pg, case_stack.case_dvid
    doc_no, clause = "京证监[2099]9号", "第五条"
    # 手插 cited_regulations(L2 默认空;仿 R2 手插 revision_notes 验证机制)
    with pg.session() as s:
        s.get(Case, dvid).cited_regulations = [{"doc_no": doc_no, "clause_path": clause}]
    try:
        assert dvid in cases_for_clauses(pg, [norm_ref(doc_no, clause)])   # 精确反查命中(真 JSONB)
        assert cases_for_clauses(pg, [norm_ref("无此文号", "第一条")]) == []  # 未命中 → []
        assert cases_for_clauses(pg, []) == []                              # 无键 → []
    finally:
        with pg.session() as s:  # 复位空,不污染其他用例
            s.get(Case, dvid).cited_regulations = []
