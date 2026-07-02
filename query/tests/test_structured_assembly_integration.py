"""T2(集成):四-Tab 装配连真栈,验字段追溯 PG 权威 + 匹配度归一 + clause_id 真实。

gate 见 conftest.indexed_stack(PIPELINE_EMBEDDING_MODEL + PG + Milvus + soffice);未起 skip。
seed 内规「合同管理办法」→ 命中制度/命中条款 有内容;案例/外规未 seed → 对应 tab 空(total=0,不崩)。
"""

from __future__ import annotations

from sqlalchemy import select

from common.pg_models import Chunk
from query.api.structured import assemble_structured, fetch_pg_context
from query.config import load_query_config
from query.retrieve.hybrid import Retriever, drop_degraded


def test_structured_traceable_to_pg(indexed_stack):
    pg, mio, ctx, _dvid, query = indexed_stack
    retr = Retriever(ctx.embedding, mio, load_query_config())
    cands = drop_degraded(retr.retrieve(query))
    case_cands = drop_degraded(retr.retrieve_cases(query))
    chunk_doc, case_rows = fetch_pg_context(pg, cands, case_cands)
    s = assemble_structured(cands, case_cands, chunk_doc, case_rows).to_dict()

    # 内规命中 → 命中条款有内容,匹配度归一在 [0,1]
    assert s["clauses"]["total"] >= 1
    for c in s["clauses"]["items"]:
        assert 0.0 <= c["match_score"] <= 1.0

    # clause_id 必属真实存在的 chunk(零编造,承 R1 引用真实性红线)
    with pg.session() as sess:
        real_ids = {c.chunk_id for c in sess.scalars(select(Chunk))}
    assert all(c["clause_id"] in real_ids for c in s["clauses"]["items"])

    # 命中制度标题追溯 PG doc_versions(seed 的「合同管理办法」)
    titles = {r["title"] for r in s["regulations"]["items"]}
    assert "合同管理办法" in titles

    # 四 Tab 恒在(未 seed 的案例/外规为空,不崩)
    for tab in ("regulations", "clauses", "regulatory_rules", "cases"):
        assert set(s[tab]) == {"total", "items"}
