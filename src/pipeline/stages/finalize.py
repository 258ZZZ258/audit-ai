"""finalize:INDEXED 后的版本原子切换(D1)。

**带外操作,非 pipeline_status 迁移**——``INDEXED`` 是终态,版本切换改的是 ``version_status``
(effective↔superseded)这个独立标量,不动状态机硬契约。由 CLI 在文档推进到 INDEXED 后显式调用
(自动触发),不被 orchestrator 轮询;不 import 其他 stage(走 index/ 共享层)。

新版到 INDEXED 且带 ``supersedes_version_id`` → 把被替代的旧版置 superseded(三步,对齐 D1 验收):
1. **PG 原子事务**(``pg_io.supersede_version``):旧版 version_status + 其 chunks chunk_status →
   superseded;新版置 effective(幂等)。
2. **Milvus**:从 PG 冷备重建旧版 chunk 行(status=superseded)upsert + flush——零重编码、**不 delete**
   (旧版仍可被 ``--include-superseded`` 检索到)。写序 PG→Milvus,PG 侧原子使整体可重放安全。
3. **下游通知**:打日志占位。

幂等/可重放:旧版已 superseded 时重跑等价无副作用(PG 再置同值;Milvus 再 upsert 同 status)。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pipeline.index import corpus_rows
from pipeline.index.pg_models import DocVersion
from pipeline.stage_base import StageContext
from pipeline.states import PipelineState

logger = logging.getLogger(__name__)

#: 触发切换的终态(到此且带 supersedes 即切换;degraded 新版同样替代旧版)。
_INDEXED_STATES = frozenset({PipelineState.INDEXED.value, PipelineState.DEGRADED_INDEXED.value})


@dataclass(frozen=True)
class FinalizeResult:
    switched: bool
    new_dvid: str
    old_dvid: str | None = None


def run(ctx: StageContext, doc_version_id: str) -> FinalizeResult:
    """对刚到 INDEXED 的新版执行版本切换;无被替代旧版 / 未到 INDEXED 则 no-op。"""
    dv = ctx.db.get(DocVersion, doc_version_id)
    if dv is None or dv.pipeline_status not in _INDEXED_STATES or not dv.supersedes_version_id:
        return FinalizeResult(False, doc_version_id)
    old_dvid = dv.supersedes_version_id

    # 1. PG 原子切换(旧版及其 chunk → superseded;新版 effective)
    ctx.db.supersede_version(old_dvid, new_dvid=doc_version_id)
    # 2. Milvus:旧版 chunk 标量改 superseded —— 从冷备重建整行 upsert(零重编码,不删)
    rows = corpus_rows.rows_from_cold(ctx.db, old_dvid, "superseded")
    if rows:
        ctx.milvus.upsert(rows)
        ctx.milvus.flush()
    # 3. 下游通知占位(生产:通知检索/比对下游旧版失效)
    logger.info("版本切换:旧版 %s 经新版 %s 置 superseded(下游通知占位)", old_dvid, doc_version_id)
    return FinalizeResult(True, doc_version_id, old_dvid)
