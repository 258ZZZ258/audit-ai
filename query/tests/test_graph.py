"""T13(单元):LangGraph 路由装配——R7 澄清 / R8 兜底 / R2–R6 占位(均不触检索/PG/LLM)。

R1 evidence 路径连真栈,见 test_graph_integration。本测只验路由分支落到正确终端节点 + 契约形态。
"""

from __future__ import annotations

import pytest

from query.config import load_query_config
from query.contract import BlockType, RouteType
from query.graph import QueryAgent
from query.llm.stub import StubLLMClient


@pytest.fixture
def agent():
    # retriever/pg=None:非 evidence 路径不触碰它们(纯函数节点)
    return QueryAgent(retriever=None, pg=None, llm=StubLLMClient(), qcfg=load_query_config())


def test_off_domain_routes_to_refuse(agent):
    res = agent.ask("今天天气怎么样")
    assert res.route_type is RouteType.REFUSE
    assert "超出" in res.answer_blocks[0].content


def test_ambiguous_routes_to_clarify(agent):
    res = agent.ask("它呢")
    assert res.route_type is RouteType.CLARIFY
    assert res.answer_blocks[0].type is BlockType.CLARIFY_QUESTION


@pytest.mark.parametrize(
    "query, route",
    [
        # R2 变更 / R3 案例已实装(走真栈,见 test_r2_change_integration / test_r3_case_integration);
        # 此处仅 R4–R6 仍占位
        ("哪些制度规定了信息披露", RouteType.ENUMERATE),
        ("二维码介绍开户是否违规", RouteType.JUDGMENTAL),
        ("哪些板块处罚高发", RouteType.STATISTICAL),
    ],
)
def test_r4_to_r6_honest_placeholder(agent, query, route):
    res = agent.ask(query)
    assert res.route_type is route  # 正确打标
    assert "暂未实装" in res.answer_blocks[0].content  # 诚实占位,不裸答
    assert "违规" not in res.answer_blocks[0].content and "合规" not in res.answer_blocks[0].content
    assert res.citations == []  # 占位不出引用


def test_case_routes_to_r3_node():
    # R3 已实装:CASE 路由落 r3_case 节点(用 fake retriever/pg,零栈)。空命中 → 明示。
    class _Retr:
        def retrieve_cases(self, q, *, include_superseded=False):
            return []

    class _Pg:
        def get_case(self, dvid):
            return None

        def get(self, model, pk):
            return None

    agent = QueryAgent(retriever=_Retr(), pg=_Pg(), llm=StubLLMClient(), qcfg=load_query_config())
    res = agent.ask("有没有类似的处罚案例")
    assert res.route_type is RouteType.CASE
    assert "未检索到" in res.answer_blocks[0].content  # 诚实明示,不裸答、不臆造
    assert res.citations == []


def test_route_only_no_retrieval(agent):
    assert agent.route_only("费用报销三个月的规定在哪里") is RouteType.EVIDENCE
