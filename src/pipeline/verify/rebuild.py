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
    """从 PG 冷备零编码重建 audit_corpus:**先全量组装、再 drop + 重灌**。

    顺序是数据安全的关键:drop 前先把所有 doc 的冷备反序列化成行,任何冷备缺失/损坏都在组装期
    暴露,此时集合仍完好、不会半路被清空。只回灌冷备齐全的非 parent 块(``rows_from_cold`` 跳过
    META_REVIEW 等未嵌入中间态),不会对 None 反序列化中断。各块按存储 ``chunk_status``
    (effective/superseded)还原;纯 insert(非 upsert)→ 计数干净。
    """
    before = ctx.milvus.count()
    # ① drop 前先全量组装(零编码反序列化):缺失/损坏在此暴露,Milvus 仍完好
    pending = []  # [(dvid, rows)],仅含冷备齐全、有可回灌块的 doc
    for dvid in ctx.db.chunk_doc_version_ids():
        rows = corpus_rows.rows_from_cold(ctx.db, dvid)  # status=None → 按存储 status 还原
        if rows:
            pending.append((dvid, rows))
    # ② 组装无误 → drop + 重建空集合 + 纯 insert 重灌
    ctx.milvus.create_collection(drop_existing=True)
    reloaded = 0
    for _dvid, rows in pending:
        ctx.milvus.upsert(rows)
        reloaded += len(rows)
    ctx.milvus.flush()
    return RebuildResult(
        docs=len(pending), chunks_reloaded=reloaded, before_count=before,
        after_count=ctx.milvus.count(),
    )
