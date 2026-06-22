"""T11(集成):R1 端到端(检索→生成→四级引用)连真栈 + stub LLM,验引用真实性 + 无裸结论。

gate 见 conftest.indexed_stack(PIPELINE_EMBEDDING_MODEL + PG + Milvus + soffice)。
"""

from __future__ import annotations

from sqlalchemy import select

from common.pg_models import Chunk
from query.config import load_query_config
from query.contract import RouteType
from query.generate.r1_evidence import generate_evidence
from query.llm.stub import StubLLMClient
from query.retrieve.hybrid import Retriever


def test_r1_end_to_end_faithful(indexed_stack):
    pg, mio, ctx, dvid, query = indexed_stack
    cands = Retriever(ctx.embedding, mio, load_query_config()).retrieve(query)
    res = generate_evidence(query, cands, pg, StubLLMClient())

    assert res.route_type is RouteType.EVIDENCE
    assert res.ai_label is True

    # 引用真实性:每条 citation 的 clause_id 必属检索候选(零编造)
    cand_ids = {c.chunk_id for c in cands}
    assert res.citations, "充分路径应有引用"
    assert all(cit.clause_id in cand_ids for cit in res.citations)

    # 四级锚点回查到位(文档级 + 状态)
    top = res.citations[0]
    assert top.doc_title == "合同管理办法"
    assert top.status == "effective"

    # 无裸结论
    text = " ".join(b.content for b in res.answer_blocks)
    assert "违规" not in text and "合规" not in text


def test_r1_citations_subset_of_pg_chunks(indexed_stack):
    pg, mio, ctx, dvid, query = indexed_stack
    cands = Retriever(ctx.embedding, mio, load_query_config()).retrieve(query)
    res = generate_evidence(query, cands, pg, StubLLMClient())
    with pg.session() as s:
        all_ids = {c.chunk_id for c in s.scalars(select(Chunk))}
    assert all(cit.clause_id in all_ids for cit in res.citations)  # 引用必为真实存在的 chunk
