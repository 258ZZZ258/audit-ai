"""S2 质检硬关卡:载 IR → 跑七指标 gate → 通过则 STRUCTURING,否则 QC_FAILED + evidence。

边缘通过带(qc_marginal)仅标记入 doc_version,不拦截。失败带 evidence(失败指标 + 定位)入队。
"""

from __future__ import annotations

from common.pg_models import DocVersion
from pipeline.qc.gate import evaluate
from pipeline.stage_base import QueueItem, QueueType, StageContext, StageResult
from pipeline.states import ErrorCode, PipelineState


def run(ctx: StageContext, doc_version_id: str) -> StageResult:
    ir = ctx.object_store.load_ir(doc_version_id)
    report = evaluate(ir, ctx.config.qc)
    _set_marginal(ctx, doc_version_id, report.marginal)

    if report.failed:
        evidence = report.to_evidence()
        return StageResult(
            next_state=PipelineState.QC_FAILED,
            error_code=ErrorCode.QC_GATE_FAILED.value,
            evidence=evidence,
            queue=QueueItem(QueueType.QC_FIX, doc_version_id, "质检未通过", evidence),
            marginal=report.marginal,
        )
    return StageResult(next_state=PipelineState.STRUCTURING, marginal=report.marginal)


def _set_marginal(ctx: StageContext, dvid: str, marginal: bool) -> None:
    if not marginal:
        return
    with ctx.db.session() as s:
        dv = s.get(DocVersion, dvid)
        if dv is not None:
            dv.qc_marginal = True
