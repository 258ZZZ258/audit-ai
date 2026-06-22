"""T13(集成):QueryAgent.ask 端到端 R1(LangGraph 全程)连真栈 + stub LLM。

gate 见 conftest.indexed_stack(PIPELINE_EMBEDDING_MODEL + PG + Milvus + soffice)。
"""

from __future__ import annotations

from sqlalchemy import select

from common.pg_models import Chunk
from query.config import load_query_config
from query.contract import RouteType
from query.graph import QueryAgent
from query.llm.stub import StubLLMClient
from query.retrieve.hybrid import Retriever


def test_agent_ask_r1_end_to_end(indexed_stack):
    pg, mio, ctx, dvid, query = indexed_stack
    agent = QueryAgent(
        retriever=Retriever(ctx.embedding, mio, load_query_config()),
        pg=pg,
        llm=StubLLMClient(),
        qcfg=load_query_config(),
    )
    res = agent.ask(query)

    assert res.route_type is RouteType.EVIDENCE
    assert res.ai_label is True
    # 引用真实性:经 LangGraph 全程后仍 clause_id ⊆ 真实 chunk(零编造)
    with pg.session() as s:
        all_ids = {c.chunk_id for c in s.scalars(select(Chunk))}
    assert res.citations and all(c.clause_id in all_ids for c in res.citations)
    # 四级锚点 + 无裸结论
    assert res.citations[0].status == "effective"
    text = " ".join(b.content for b in res.answer_blocks)
    assert "违规" not in text and "合规" not in text


class _NoCiteLLM:
    """模拟网关 LLM 返回无忠实引用(cited 为空)——不可信输出边界测试。"""

    def chat_json(self, system: str, user: str) -> dict:
        return {"answer": "(无依据答复)", "cited_clause_ids": []}


def test_agent_ungrounded_llm_refuses(indexed_stack):
    # finding 2:检索到候选但 LLM 无忠实引用 → 绝不出 evidence 裸答 → 降级覆盖拒答
    pg, mio, ctx, dvid, query = indexed_stack
    agent = QueryAgent(
        retriever=Retriever(ctx.embedding, mio, load_query_config()),
        pg=pg,
        llm=_NoCiteLLM(),
        qcfg=load_query_config(),
    )
    res = agent.ask(query)
    assert res.route_type is RouteType.REFUSE
    assert res.exhausted_scope  # 非空(可解释)
    assert res.citations == [] or all(c.clause_id for c in res.citations)


class _VerdictLLM:
    """模拟网关 LLM 返回合法引用 + **裸结论**答复——不可信输出边界(no-bare-conclusion 后检)。"""

    def chat_json(self, system: str, user: str) -> dict:
        import re

        ids = re.findall(r"\[\[clause_id:([^\]]+)\]\]", user)
        return {"answer": "该行为违规,属于不合规操作。", "cited_clause_ids": ids[:1]}


def test_agent_evidence_sanitizes_bare_conclusion(indexed_stack):
    # 复审 finding:有忠实引用但 LLM 输出裸结论 → 出 evidence 但答复经后检替中性,绝不漏裸结论
    pg, mio, ctx, dvid, query = indexed_stack
    agent = QueryAgent(
        retriever=Retriever(ctx.embedding, mio, load_query_config()),
        pg=pg,
        llm=_VerdictLLM(),
        qcfg=load_query_config(),
    )
    res = agent.ask(query)
    assert res.route_type is RouteType.EVIDENCE  # 有真实引用 → 仍是依据路径
    assert res.citations  # 引用保留
    text = " ".join(b.content for b in res.answer_blocks)
    assert all(t not in text for t in ("违规", "违法", "合规", "合法"))  # 裸结论被后检剔除
