"""S4 元数据:L1 规则抽取 + 与 manifest 交叉校验。

L2(LLM 辅助)默认关(``toggles.l2_enabled``,C2 不调 LLM)。L1 值不持久化:仅交叉校验,manifest 为权威。

**双模式人工闸**(详见 devlog《META_REVIEW 双模式》):
- **A 模式**(默认,``auto_confirm_meta_no_conflict`` 关):所有件 → META_REVIEW + meta_confirm 队列,
  每篇进权威语料都有具名人工担责(权威边界闸)。
- **B 模式(B-严)**(开关开):例外式审核——**无冲突的全新件**直接 → EMBEDDING 自动放行;
  但**有冲突件**、以及**带 ``supersedes_version_id`` 的修订件**(supersede 旧版是最有后果的权威变更,
  即便无冲突也该有人点头)仍进 META_REVIEW。
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
    evidence = {"conflicts": [asdict(c) for c in conflicts]}
    # B-严:无冲突**且非修订件**才自动放行;修订件(带 supersedes)即便无冲突仍入闸,
    # 因 finalize 会 supersede 旧版——这一最有后果的权威变更须有人点头(见 devlog 双模式)。
    if (
        not conflicts
        and ctx.config.toggles.auto_confirm_meta_no_conflict
        and not dv.supersedes_version_id
    ):
        return StageResult(
            next_state=PipelineState.EMBEDDING,
            evidence={**evidence, "auto_confirmed": True},
        )

    # 入 meta_confirm 队列。冲突件 evidence 带 conflicts 供重点审;无冲突件为常规确认(conflicts 空);
    # 修订件即便无冲突也入闸(B-严)——reason 标明是哪种,便于 queue/report 区分。
    if conflicts:
        reason = "L1/manifest 元数据冲突"
    elif dv.supersedes_version_id:
        reason = "修订件待人工确认(无冲突,supersede 旧版需放行)"
    else:
        reason = "元数据待人工确认(无冲突)"
    return StageResult(
        next_state=PipelineState.META_REVIEW,
        evidence=evidence,
        queue=QueueItem(QueueType.META_CONFIRM, doc_version_id, reason, evidence),
    )
