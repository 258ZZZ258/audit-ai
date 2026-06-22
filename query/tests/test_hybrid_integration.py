"""T5:混合检索连真栈——命中 ingest 件、带 clause_id + 分区/检索模式标记。

gate 见 conftest.indexed_stack(PIPELINE_EMBEDDING_MODEL + PG + Milvus + soffice)。
"""

from __future__ import annotations

from sqlalchemy import select

from common.pg_models import Chunk
from query.config import load_query_config
from query.retrieve.hybrid import Retriever


def _clause_chunk_ids(pg, dvid: str) -> set[str]:
    with pg.session() as s:
        return {
            c.chunk_id
            for c in s.scalars(
                select(Chunk).where(Chunk.doc_version_id == dvid, Chunk.is_parent.is_(False))
            )
        }


def test_hybrid_retrieve_hits_ingested_doc(indexed_stack):
    pg, mio, ctx, dvid, query = indexed_stack
    r = Retriever(ctx.embedding, mio, load_query_config())
    cands = r.retrieve(query)

    assert cands, "应有候选命中"
    hit_ids = {c.chunk_id for c in cands}
    assert hit_ids & _clause_chunk_ids(pg, dvid), "未命中 ingest 件的任何 chunk"

    top = cands[0]
    assert top.chunk_id  # 带 clause_id(=chunk_id)
    assert top.retrieval_mode in ("hybrid", "dense_only")  # 检索模式标记在(dense-only 兜底可观测)
    # 仅 effective 可见(staging 不可见是硬契约,由 milvus_io status 前置过滤保证)
    assert all(c.corpus_type in ("P-INT", "P-EXT") for c in cands)


def test_partition_quota_caps_recall(indexed_stack):
    pg, mio, ctx, dvid, query = indexed_stack
    cfg = load_query_config()
    cands = Retriever(ctx.embedding, mio, cfg).retrieve(query)
    assert len(cands) <= cfg.topk  # 合并后裁到 topk(§5.2 配额合并)
