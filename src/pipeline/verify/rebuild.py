"""rebuild(V6,V0.1 §12.3/§21.2):drop collection → 从 PG chunks + bytea 冷备全量重灌(零编码)。

演示「PG 权威、Milvus 可重建、Milvus 不担数据安全」:删集合后,所有块向量从 PG 冷备
(`dense_vec_cold`/`sparse_vec_cold`)反序列化重灌(`corpus_rows.rows_from_cold`,**不重编码**),
各块按存储 `chunk_status`(effective/superseded)还原。纯 insert(非 upsert)→ 计数干净;向量 bit
一致 → 同查询 top10 一致(V6),由测试断言。
"""

from __future__ import annotations

from dataclasses import dataclass

from pipeline.index import corpus_rows
from pipeline.stage_base import StageContext


@dataclass
class RebuildResult:
    docs: int  # 重灌的 doc_version 数
    chunks_reloaded: int
    before_count: int  # drop 前 Milvus num_entities(参考)
    after_count: int  # 重灌 flush 后 num_entities


def run_rebuild(ctx: StageContext) -> RebuildResult:
    """drop audit_corpus → 遍历所有有 chunk 的 doc_version,从冷备零编码重灌 + flush。"""
    before = ctx.milvus.count()
    ctx.milvus.create_collection(drop_existing=True)  # drop + 重建空集合 + 索引
    dvids = ctx.db.chunk_doc_version_ids()
    reloaded = 0
    for dvid in dvids:
        rows = corpus_rows.rows_from_cold(ctx.db, dvid)  # status=None → 按存储 status 还原,零编码
        if rows:
            ctx.milvus.upsert(rows)
            reloaded += len(rows)
    ctx.milvus.flush()
    return RebuildResult(
        docs=len(dvids), chunks_reloaded=reloaded, before_count=before,
        after_count=ctx.milvus.count(),
    )
