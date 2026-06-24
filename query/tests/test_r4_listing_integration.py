"""R4-T5(集成):R4 多文档列举端到端连真栈——跨文档聚合 + E1 义务过滤 + Milvus extra_expr 真过滤。

gate:PIPELINE_EMBEDDING_MODEL + PG + Milvus + soffice(``enumerate_stack`` fixture)。未满足即 skip。
红线:条款逐字来自命中、四级锚点 PG 权威(非 Milvus 截断 / 非 LLM);不保证穷举外规边界声明在;
E1 义务过滤 consumed-when-present(doc_b 无义务标 → 义务查询被剔除);extra_expr biz 过滤经真 Milvus。
"""

from __future__ import annotations

import json

import pytest

from query.config import load_query_config
from query.contract import BlockType, RouteType
from query.listing.r4_listing import answer_enumerate
from query.retrieve.hybrid import Retriever


@pytest.fixture(autouse=True)
def _ensure_milvus_connected(enumerate_stack):
    """重连 Milvus(幂等):pymilvus 全局 "default" 连接被 test_r2 模块级 teardown 断开;
    本文件按字母序在 r2/r3 之后跑,检索前须重连,否则 ConnectionNotExist(沿用 R3 预案)。
    """
    enumerate_stack.mio.connect()


def _retr(es):
    return Retriever(es.ctx.embedding, es.mio, load_query_config())


def _table_rows(res):
    block = next(b for b in res.answer_blocks if b.type is BlockType.TABLE)
    return json.loads(block.content)


def _titles(res):
    return {row[0] for row in _table_rows(res)["rows"]}  # 列 0 = 制度名称


def test_enumerate_aggregates_across_documents(enumerate_stack):
    es = enumerate_stack
    res = answer_enumerate("哪些制度规定了信息披露", _retr(es), es.pg)
    assert res.route_type is RouteType.ENUMERATE
    titles = _titles(res)
    # 两件同主题制度各成一行(跨文档聚合)
    assert "信息披露管理办法" in titles
    assert "信息披露事务管理细则" in titles
    # 边界声明(§15-③)
    assert "不保证穷举外规" in _table_rows(res)["note"]
    # 四级锚点真数据(PG 权威):至少一条 citation 带条款路径 + 页码 + effective
    cit = next(c for c in res.citations if c.doc_title in titles)
    assert cit.clause_path and cit.page_start is not None and cit.status == "effective"


def test_obligation_filter_drops_non_obligation_doc(enumerate_stack):
    es = enumerate_stack
    # 义务意图查询("要求")→ E1 后过滤:doc_b 无义务标 → 剔除;doc_a(应当条款)保留
    res = answer_enumerate("列出所有关于信息披露的要求", _retr(es), es.pg)
    assert res.route_type is RouteType.ENUMERATE
    titles = _titles(res)
    assert "信息披露管理办法" in titles          # 含义务条款 → 保留
    assert "信息披露事务管理细则" not in titles    # 无义务标 → E1 过滤剔除


def test_biz_domain_extra_expr_filters_via_milvus(enumerate_stack):
    es = enumerate_stack
    # 正:biz_domain code 命中 → 列举有结果(extra_expr 经真 Milvus 过滤,不误杀)
    pos = answer_enumerate(
        f"哪些制度规定了{es.biz_code}信息披露", _retr(es), es.pg, biz_terms=[es.biz_code]
    )
    assert pos.route_type is RouteType.ENUMERATE
    assert "信息披露管理办法" in _titles(pos)
    # 负:不存在的 biz_domain code → Milvus 过滤后 0 命中 → 覆盖拒答(证 extra_expr 真下推 Milvus)
    neg = answer_enumerate(
        "哪些制度规定了NOSUCHBIZ信息披露", _retr(es), es.pg, biz_terms=["NOSUCHBIZ"]
    )
    assert neg.route_type is RouteType.REFUSE
    assert neg.exhausted_scope  # 可解释拒答
