"""S5 嵌入索引(装配):EMBEDDING(嵌入 + 冷备 + Milvus staging upsert)→ INDEXING(flush + 校验
+ staging→effective + 终态)。

写序契约:PG(冷备)→ Milvus upsert → flush → set INDEXED。staging 期被 search 的 status==effective
滤掉(半成品不可见),index 阶段从 PG 冷备重 upsert 翻转为 effective(零重编码,同 rebuild)。
父块(节级)仅 PG、不入 Milvus;表格块入。degraded 件 chunk 标 degraded,终于 DEGRADED_INDEXED。
"""

from __future__ import annotations

from datetime import date

from common.pg_models import DocVersion
from pipeline.index.corpus_rows import build_rows, indexable_chunks, rows_from_cold_strict
from pipeline.index.milvus_io import dense_to_bytes, sparse_to_bytes
from pipeline.meta.version_chain import live_status
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
    """INDEXING:flush → 全块就绪(count==)→ 从冷备重 upsert 上线态 + flush + 翻状态 → 终态。

    上线态由 ``live_status`` 定(§1.1/§7.2):生效日在未来 → upcoming(默认检索不可见、不替代旧版,
    待 ``demo activate`` 翻 effective),否则 effective。version_status 同步翻同值。
    """
    dv = ctx.db.get(DocVersion, doc_version_id)
    live = live_status(dv.effective_date, date.today())
    chunks = indexable_chunks(ctx.db, doc_version_id)
    if chunks:  # 从 PG 冷备重建上线行 upsert(零重编码),按 chunk_id 覆盖 embed 的 staging upsert
        # 严格:任一块缺冷备即抛 → 文档不进 INDEXED(不可在缺投影下翻状态)。维护命令才用跳过式。
        ctx.milvus.upsert(rows_from_cold_strict(ctx.db, doc_version_id, live))
        # ⚠ 单次 flush(原每件 2 次 → 1 次):上线态 upsert 覆盖 staging 后只 flush 一次——
        # count 校验(下)与 durability(flush-before-INDEXED)不变量都保,Milvus flush 压力减半,
        # 缓解 standalone 在批量 per-doc flush 下的 flush 积压卡死(根因)。
        ctx.milvus.flush()
        indexed = ctx.milvus.count(doc_version_id)
        if indexed != len(chunks):  # 文档级全块就绪校验(写序不变量)
            raise RuntimeError(f"索引不齐:PG {len(chunks)} != Milvus {indexed}({doc_version_id})")
    ctx.db.set_chunk_status(doc_version_id, live)
    ctx.db.set_version_status(doc_version_id, live)
    terminal = PipelineState.DEGRADED_INDEXED if dv.degraded else PipelineState.INDEXED
    return StageResult(next_state=terminal)
