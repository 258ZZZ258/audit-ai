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
