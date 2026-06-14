"""S4 元数据:L1 规则抽取 + 与 manifest 交叉校验。均 → META_REVIEW + meta_confirm 队列(统一人工闸)。

L2(LLM 辅助)默认关(``toggles.l2_enabled``,C2 不调 LLM)。L1 值不持久化:仅交叉校验,manifest 为权威。

**META_REVIEW 是所有件的强制人工闸**(状态机唯一出边,每件需人工 confirm 才走 EMBEDDING),故**每件都入
meta_confirm 队列**——review_queue 是所有人工动作的唯一入口(CLAUDE.md)。冲突件 evidence 带 conflicts
供重点审,无冲突件为常规确认(conflicts 空)。``demo meta confirm``(C7)对该队列项做 approve 处置放行。
"""

from __future__ import annotations

from dataclasses import asdict

from pipeline.index.pg_models import DocVersion
from pipeline.meta import l1_rules
from pipeline.stage_base import QueueItem, QueueType, StageContext, StageResult
from pipeline.states import PipelineState


def run(ctx: StageContext, doc_version_id: str) -> StageResult:
    ir = ctx.object_store.load_ir(doc_version_id)
    dv = ctx.db.get(DocVersion, doc_version_id)
    issuers = [(i.code, i.name) for i in ctx.db.get_issuers()]

    meta = l1_rules.extract(ir, issuers)
    conflicts = l1_rules.cross_check(
        meta,
        doc_number=dv.doc_number,
        issue_date=dv.issue_date,
        issuer_code=l1_rules.resolve_issuer(dv.issuer, issuers),
        title=dv.title,
    )
    # META_REVIEW 是全件强制人工闸 → 每件都入 meta_confirm 队列(统一队列是人工动作唯一入口);
    # 冲突件 evidence 带 conflicts 供重点审,无冲突件为常规确认(conflicts 空)。
    evidence = {"conflicts": [asdict(c) for c in conflicts]}
    reason = "L1/manifest 元数据冲突" if conflicts else "元数据待人工确认(无冲突)"
    return StageResult(
        next_state=PipelineState.META_REVIEW,
        evidence=evidence,
        queue=QueueItem(QueueType.META_CONFIRM, doc_version_id, reason, evidence),
    )
