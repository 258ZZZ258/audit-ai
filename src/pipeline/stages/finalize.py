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
from pipeline.index.pg_models import DocVersion, PipelineEvent
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
    """INDEXED 后:① 带 supersedes 则版本切换 ② 总是跑 T2/T4 评测留痕(§9)。未到 INDEXED 则 no-op。"""
    dv = ctx.db.get(DocVersion, doc_version_id)
    if dv is None or dv.pipeline_status not in _INDEXED_STATES:
        return FinalizeResult(False, doc_version_id)
    old_dvid = dv.supersedes_version_id

    if old_dvid:  # 版本原子切换(旧版置 superseded)
        # PG 原子切换(旧版及其 chunk → superseded;新版 effective)
        ctx.db.supersede_version(old_dvid, new_dvid=doc_version_id)
        # Milvus:旧版 chunk 标量改 superseded —— 从冷备重建整行 upsert(零重编码,不删)
        rows = corpus_rows.rows_from_cold(ctx.db, old_dvid, "superseded")
        if rows:
            ctx.milvus.upsert(rows)
            ctx.milvus.flush()
        # 下游通知占位(生产:通知检索/比对下游旧版失效)
        logger.info("版本切换:旧版 %s 经新版 %s 置 superseded", old_dvid, doc_version_id)

    _run_verify(ctx, doc_version_id)  # T2 冒烟 + T4 回放,留痕入 pipeline_events(评测组件无阻断权)
    return FinalizeResult(bool(old_dvid), doc_version_id, old_dvid)


def _run_verify(ctx: StageContext, dvid: str) -> None:
    """INDEXED 后跑 T2 冒烟 + T4 回放,留痕 `pipeline_events.detail['verify']`(供 report 聚合,§9)。

    finalize 仅在 worker ctx(含 embedding+milvus)到 INDEXED 时被调用,故 smoke 复用已载模型。
    **评测组件对终态无阻断权**:任何异常吞掉、只记日志,不改 pipeline_status。
    """
    try:
        from pipeline.verify.anchor_replay import run_replay
        from pipeline.verify.smoke import run_smoke

        t4 = run_replay(ctx, [dvid])
        t2_hit = None
        if ctx.embedding is not None and ctx.milvus is not None:
            sm = run_smoke(ctx, [dvid])
            t2_hit = sm.per_doc[0]["hit"] if sm.per_doc else None
        detail = {"verify": {"t2_hit": t2_hit, "t4_pass": t4.passed, "t4_rate": t4.pass_rate}}
        with ctx.db.session() as s:
            cur = s.get(DocVersion, dvid)
            s.add(
                PipelineEvent(
                    doc_version_id=dvid, from_state=cur.pipeline_status,
                    to_state=cur.pipeline_status, actor="finalize", detail=detail,
                )
            )
        logger.info("finalize 评测 %s:T2 hit=%s T4 pass=%s", dvid, t2_hit, t4.passed)
    except Exception as e:  # 评测失败不阻断终态(V0.1 §21.2)
        logger.warning("finalize T2/T4 评测失败(不阻断):%s", e)
