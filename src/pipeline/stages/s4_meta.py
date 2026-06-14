"""S4 元数据:L1 规则抽取 + 与 manifest 交叉校验。均 → META_REVIEW;冲突另入 meta_confirm 队列。

L2(LLM 辅助)默认关(``toggles.l2_enabled``,C2 不调 LLM)。L1 值不持久化——仅交叉校验,manifest
仍为权威;冲突详情入 meta_confirm 队列 evidence 供人审。STRUCTURING → META_REVIEW 是状态机唯一出边,
故无冲突件也停 META_REVIEW(经 CLI meta confirm 放行,C7)。
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
    if not conflicts:
        return StageResult(next_state=PipelineState.META_REVIEW)

    evidence = {"conflicts": [asdict(c) for c in conflicts]}
    return StageResult(
        next_state=PipelineState.META_REVIEW,
        evidence=evidence,
        queue=QueueItem(
            QueueType.META_CONFIRM, doc_version_id, "L1/manifest 元数据冲突", evidence
        ),
    )
