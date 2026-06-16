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
        # 先严格组装旧版冷备行(任一块缺冷备即抛,此时 PG 未动 → 整体可重试、不留 PG 超前 Milvus
        # 的残留)。冷备齐全才继续:PG 原子切换 → Milvus 旧版 chunk 标量改 superseded(零重编码,不删)。
        rows = corpus_rows.rows_from_cold_strict(ctx.db, old_dvid, "superseded")
        ctx.db.supersede_version(old_dvid, new_dvid=doc_version_id)
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
    **评测组件对终态无阻断权**:评测异常(源文件/渲染件缺失、解析异常等)不改 pipeline_status,但
    **必须据实留痕为失败**——否则该 doc 在 report 聚合里整条消失,T4/T2 通过率显 None 掩盖失败,违背
    V0.1 §21.2「不阻断终态,但写入报告」。故 T4 没跑出来即记 ``t4_pass=False`` + ``error``;若仅 T2
    崩,已得的 T4 结果仍保留。
    """
    t2_hit = None
    t4_pass = None
    t4_rate = None
    error = None
    try:
        from pipeline.verify.anchor_replay import run_replay
        from pipeline.verify.smoke import run_smoke

        t4 = run_replay(ctx, [dvid])
        t4_pass, t4_rate = t4.passed, t4.pass_rate
        if ctx.embedding is not None and ctx.milvus is not None:
            sm = run_smoke(ctx, [dvid])
            t2_hit = sm.per_doc[0]["hit"] if sm.per_doc else None
    except Exception as e:  # 不阻断终态,但记为失败(否则 report 聚合不到 → 显 None 掩盖)
        error = str(e)
        if t4_pass is None:  # T4 都没跑出来 → 计失败,而非从报告里消失
            t4_pass = False
        logger.warning("finalize T2/T4 评测异常(不阻断,记入报告):%s", e)

    detail = {"verify": {"t2_hit": t2_hit, "t4_pass": t4_pass, "t4_rate": t4_rate}}
    if error is not None:
        detail["verify"]["error"] = error
    try:
        with ctx.db.session() as s:
            cur = s.get(DocVersion, dvid)
            s.add(
                PipelineEvent(
                    doc_version_id=dvid, from_state=cur.pipeline_status,
                    to_state=cur.pipeline_status, actor="finalize", detail=detail,
                )
            )
        logger.info(
            "finalize 评测 %s:T2 hit=%s T4 pass=%s%s",
            dvid, t2_hit, t4_pass, f" err={error}" if error else "",
        )
    except Exception as e:  # 连留痕都写不进(PG 异常)——只能日志,仍不阻断终态
        logger.warning("finalize 评测留痕写入失败(不阻断):%s / %s", dvid, e)
