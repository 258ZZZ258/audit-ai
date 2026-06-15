"""S5 嵌入索引(装配):EMBEDDING(嵌入 + 冷备 + Milvus staging upsert)→ INDEXING(flush + 校验
+ staging→effective + 终态)。

写序契约:PG(冷备)→ Milvus upsert → flush → set INDEXED。staging 期被 search 的 status==effective
滤掉(半成品不可见),index 阶段从 PG 冷备重 upsert 翻转为 effective(零重编码,同 rebuild)。
父块(节级)仅 PG、不入 Milvus;表格块入。degraded 件 chunk 标 degraded,终于 DEGRADED_INDEXED。
"""

from __future__ import annotations

from pipeline.index.corpus_rows import build_rows, indexable_chunks, rows_from_cold
from pipeline.index.milvus_io import dense_to_bytes, sparse_to_bytes
from pipeline.index.pg_models import DocVersion
from pipeline.stage_base import StageContext, StageResult
from pipeline.states import PipelineState


def embed(ctx: StageContext, doc_version_id: str) -> StageResult:
    """EMBEDDING:嵌入非 parent 块 → 冷备写 PG → Milvus upsert(staging)→ INDEXING。"""
    chunks = indexable_chunks(ctx.db, doc_version_id)
    if chunks:
        embs = ctx.embedding.embed([c.text for c in chunks])
        ctx.db.write_cold_vectors(
            {
                c.chunk_id: (dense_to_bytes(e.dense), sparse_to_bytes(e.sparse))
                for c, e in zip(chunks, embs, strict=True)
            }
        )
        rows = build_rows(
            ctx.db, doc_version_id, chunks, [(e.dense, e.sparse) for e in embs], "staging"
        )
        ctx.milvus.upsert(rows)
    return StageResult(next_state=PipelineState.INDEXING)


def index(ctx: StageContext, doc_version_id: str) -> StageResult:
    """INDEXING:flush → 全块就绪(count==)→ 从冷备重 upsert effective + flush + 翻状态 → 终态。"""
    dv = ctx.db.get(DocVersion, doc_version_id)
    ctx.milvus.flush()  # 封 embed 的 staging upsert
    chunks = indexable_chunks(ctx.db, doc_version_id)
    indexed = ctx.milvus.count(doc_version_id)
    if indexed != len(chunks):  # 文档级全块就绪校验(写序不变量)
        raise RuntimeError(f"索引不齐:PG {len(chunks)} != Milvus {indexed}({doc_version_id})")
    if chunks:  # 从 PG 冷备重建 effective 行 upsert(零重编码)→ 翻转可见
        ctx.milvus.upsert(rows_from_cold(ctx.db, doc_version_id, "effective"))
        ctx.milvus.flush()
    ctx.db.set_chunk_status(doc_version_id, "effective")
    terminal = PipelineState.DEGRADED_INDEXED if dv.degraded else PipelineState.INDEXED
    return StageResult(next_state=terminal)
