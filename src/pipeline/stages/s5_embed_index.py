"""S5 嵌入索引(装配):EMBEDDING(嵌入 + 冷备 + Milvus staging upsert)→ INDEXING(flush + 校验
+ staging→effective + 终态)。

写序契约:PG(冷备)→ Milvus upsert → flush → set INDEXED。staging 期被 search 的 status==effective
滤掉(半成品不可见),index 阶段从 PG 冷备重 upsert 翻转为 effective(零重编码,同 rebuild)。
父块(节级)仅 PG、不入 Milvus;表格块入。degraded 件 chunk 标 degraded,终于 DEGRADED_INDEXED。
"""

from __future__ import annotations

from pipeline.index.milvus_io import (
    CorpusRow,
    dense_from_bytes,
    dense_to_bytes,
    sparse_from_bytes,
    sparse_to_bytes,
)
from pipeline.index.pg_models import Chunk, Document, DocVersion
from pipeline.stage_base import StageContext, StageResult
from pipeline.states import PipelineState


def embed(ctx: StageContext, doc_version_id: str) -> StageResult:
    """EMBEDDING:嵌入非 parent 块 → 冷备写 PG → Milvus upsert(staging)→ INDEXING。"""
    chunks = _indexable(ctx, doc_version_id)
    if chunks:
        embs = ctx.embedding.embed([c.text for c in chunks])
        ctx.db.write_cold_vectors(
            {
                c.chunk_id: (dense_to_bytes(e.dense), sparse_to_bytes(e.sparse))
                for c, e in zip(chunks, embs, strict=True)
            }
        )
        rows = _rows(ctx, doc_version_id, chunks, [(e.dense, e.sparse) for e in embs], "staging")
        ctx.milvus.upsert(rows)
    return StageResult(next_state=PipelineState.INDEXING)


def index(ctx: StageContext, doc_version_id: str) -> StageResult:
    """INDEXING:flush → 全块就绪(count==)→ 从冷备重 upsert effective + flush + 翻状态 → 终态。"""
    dv = ctx.db.get(DocVersion, doc_version_id)
    ctx.milvus.flush()  # 封 embed 的 staging upsert
    chunks = _indexable(ctx, doc_version_id)
    indexed = ctx.milvus.count(doc_version_id)
    if indexed != len(chunks):  # 文档级全块就绪校验(写序不变量)
        raise RuntimeError(f"索引不齐:PG {len(chunks)} != Milvus {indexed}({doc_version_id})")
    if chunks:  # 从 PG 冷备重建 effective 行 upsert(零重编码)→ 翻转可见
        vectors = [
            (dense_from_bytes(c.dense_vec_cold), sparse_from_bytes(c.sparse_vec_cold))
            for c in chunks
        ]
        ctx.milvus.upsert(_rows(ctx, doc_version_id, chunks, vectors, "effective"))
        ctx.milvus.flush()
    ctx.db.set_chunk_status(doc_version_id, "effective")
    terminal = PipelineState.DEGRADED_INDEXED if dv.degraded else PipelineState.INDEXED
    return StageResult(next_state=terminal)


def _indexable(ctx: StageContext, dvid: str) -> list[Chunk]:
    """非 parent 块(parent=节级仅 PG;表格块入 Milvus)。"""
    return [c for c in ctx.db.get_chunks(dvid) if not c.is_parent]


def _rows(
    ctx: StageContext,
    dvid: str,
    chunks: list[Chunk],
    vectors: list[tuple[list[float], dict]],
    status: str,
) -> list[CorpusRow]:
    dv = ctx.db.get(DocVersion, dvid)
    doc = ctx.db.get(Document, dv.logical_id)
    corpus = (doc.corpus_type if doc else "") or ""  # corpus_type 在 Document(逻辑文档)
    issuer_level = _issuer_level(ctx, dv)
    return [
        CorpusRow(
            chunk_id=c.chunk_id, dense=dense, sparse=sparse,
            doc_version_id=dvid, corpus_type=corpus, status=status,
            perm_tag=dv.perm_tag or "", biz_domain=dv.biz_domain or "",
            issuer_level=issuer_level, clause_path=c.clause_path or "",
            page_start=c.page_start or 0, degraded=bool(c.degraded),
        )
        for c, (dense, sparse) in zip(chunks, vectors, strict=True)
    ]


def _issuer_level(ctx: StageContext, dv: DocVersion) -> str:
    """dv.issuer(code 或 name)→ 字典 issuer_level;解析不出为空串(Milvus VARCHAR 不收 None)。"""
    v = (dv.issuer or "").strip()
    if not v:
        return ""
    for i in ctx.db.get_issuers():
        if i.code == v or i.name == v:
            return i.issuer_level or ""
    return ""
