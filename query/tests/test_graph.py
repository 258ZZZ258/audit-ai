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


# ── 附挂门控(§6.3 适用边界):仅充分 evidence + 非概念判断型;拒答/关闭不挂(零栈)──────
class _OneCaseRetr:
    def retrieve_cases(self, q, *, include_superseded=False):
        from query.retrieve.hybrid import Candidate

        return [Candidate("c1", 1.0, "P-CASE", "DV1", None, None, False, "hybrid")]


class _OneCasePg:
    def get_case(self, dvid):
        from types import SimpleNamespace

        return SimpleNamespace(
            doc_version_id=dvid, penalty_org="XX证监局", penalty_date=None, respondent="XX公司",
            penalty_type="罚款", amount_wan=None, violation_category=None, cited_regulations=[],
        )

    def get(self, model, pk):
        return None

    def session(self):  # 精确反查走 fake;citations=[] 时不触达
        raise AssertionError("不应触达 PG session")


def _agent(attach_cases=True):
    qcfg = load_query_config().model_copy(update={"attach_cases": attach_cases})
    return QueryAgent(_OneCaseRetr(), _OneCasePg(), StubLLMClient(), qcfg)


def _evidence_res():
    from query.contract import AnswerBlock, QueryResult

    return QueryResult(RouteType.EVIDENCE, answer_blocks=[AnswerBlock(BlockType.TEXT, "答")])


def _cards(res):
    return [b for b in res.answer_blocks if b.type is BlockType.CASE_CARD]


def test_attach_on_evidence_non_definition():
    from query.state import QueryState

    st = QueryState("q", scene={"scene_type": "evidence"})
    res = _agent()._maybe_attach_cases(st, _evidence_res())
    assert len(_cards(res)) == 1   # 充分 evidence + 非 definition → 附挂


def test_no_attach_definition_scene():
    from query.state import QueryState

    st = QueryState("q", scene={"scene_type": "definition"})
    res = _agent()._maybe_attach_cases(st, _evidence_res())
    assert _cards(res) == []   # 概念判断型不附挂(§6.3 适用边界)


def test_no_attach_when_refuse_route():
    from query.contract import AnswerBlock, QueryResult
    from query.state import QueryState

    refuse = QueryResult(RouteType.REFUSE, answer_blocks=[AnswerBlock(BlockType.TEXT, "拒")])
    res = _agent()._maybe_attach_cases(QueryState("q", scene={"scene_type": "evidence"}), refuse)
    assert _cards(res) == []   # 拒答/降级不附挂


def test_no_attach_when_toggle_off():
    from query.state import QueryState

    res = _agent(attach_cases=False)._maybe_attach_cases(
        QueryState("q", scene={"scene_type": "evidence"}), _evidence_res()
    )
    assert _cards(res) == []   # 开关关闭 → 不附挂
