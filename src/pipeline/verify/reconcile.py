"""对账(支撑 V6,V0.1 §12.2/§21.2):逐 doc_version 比对 PG 与 Milvus 块数,不平以 PG 为准重灌。

逐 doc 比 PG 非 parent chunk 数 vs `MilvusIO.count(dvid)`(query-by-PK 准确;**不用**全集
`num_entities`——upsert churn 使其虚高)。不平 → 记 `E701` + `milvus.delete` 清旧投影 + 从 PG 冷备
`rows_from_cold`(按各 chunk 存储 status 还原,零编码)重灌 + flush + 复检。对终态无阻断权。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pipeline.index import corpus_rows
from pipeline.stage_base import StageContext

E_RECONCILE_MISMATCH = "E701"


@dataclass
class ReconcileResult:
    consistent: bool  # 重灌后是否全部一致
    # 每条:{dvid, pg, milvus, reconciled, after?, error_code?}
    per_doc: list[dict] = field(default_factory=list)


def run_reconcile(ctx: StageContext, doc_version_ids: list[str]) -> ReconcileResult:
    per_doc: list[dict] = []
    consistent = True
    for dvid in doc_version_ids:
        pg_n = len(corpus_rows.indexable_chunks(ctx.db, dvid))  # 入 Milvus 的(非 parent)
        m_n = ctx.milvus.count(dvid)  # query-by-PK,准确
        rec: dict = {"dvid": dvid, "pg": pg_n, "milvus": m_n, "reconciled": False}
        if pg_n != m_n:
            rec["error_code"] = E_RECONCILE_MISMATCH
            ctx.milvus.delete(dvid)  # 以 PG 为准:清旧投影
            ctx.milvus.flush()
            rows = corpus_rows.rows_from_cold(ctx.db, dvid)  # status=None → 保各块原状态
            if rows:
                ctx.milvus.upsert(rows)
                ctx.milvus.flush()
            rec["reconciled"] = True
            rec["after"] = ctx.milvus.count(dvid)
            if rec["after"] != pg_n:
                consistent = False
        per_doc.append(rec)
    return ReconcileResult(consistent=consistent, per_doc=per_doc)
