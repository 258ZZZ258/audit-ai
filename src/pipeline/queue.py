"""统一审核队列处置流(所有人工动作的唯一领域入口)。

review_queue 承载三类 queue_type(qc_fix / quarantine / meta_confirm);一次处置
(fix / degrade / reject / release / approve)是一个**三写原子单元**:状态迁移 + 写
``pipeline_events``(经 pg_io.transition)→ 写 ``remediation_records`` 审计 → 关闭队列行。
三者在同一事务内(pg_io.transition 的 session 注入):任一失败整事务回滚,不留半处置态。

校验两层:queue_type ↔ disposition 相容性(本模块,挡跨类型误操作);state 级合法性
(pg_io.transition 的 can_transition,非法迁移 → ValueError 回滚)。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from pipeline.index.pg_io import PgIO
from pipeline.index.pg_models import DocVersion, RemediationRecord, ReviewQueue
from pipeline.states import PipelineState

_PS = PipelineState

#: 处置 → 目标态(state 级合法性最终由 pg_io.transition 的 can_transition 把关)。
DISPOSITION_TARGET: dict[str, PipelineState] = {
    "fix": _PS.QC_PENDING,  # 补录 IR 后重入质检
    "degrade": _PS.DEGRADED_INDEXED,  # 降级入库(终态)
    "reject": _PS.REJECTED,  # 退回(终态)
    "release": _PS.PARSING,  # 隔离裁决后重入解析
    "approve": _PS.EMBEDDING,  # META_REVIEW 关卡放行
}

#: 各 queue_type 允许的处置(挡跨类型误操作,如对 qc_fix 件 approve)。
ALLOWED_DISPOSITIONS: dict[str, frozenset[str]] = {
    "qc_fix": frozenset({"fix", "degrade", "reject"}),  # QC_FAILED / PARSE_FAILED
    "quarantine": frozenset({"release", "reject"}),  # QUARANTINED
    "meta_confirm": frozenset({"approve", "reject"}),  # META_REVIEW
}


@dataclass(frozen=True)
class DispositionOutcome:
    """处置结果(供 CLI 报告)。"""

    queue_id: str
    doc_version_id: str
    disposition: str
    before_state: str
    after_state: str


def dispose(
    pg: PgIO, queue_id: str, disposition: str, *, operator: str, reason: str | None = None
) -> DispositionOutcome:
    """对一条 review_queue 行执行处置:校验 → 同一事务内迁移 + 写 remediation + 关单。

    抛 ``KeyError`` 队列项不存在;抛 ``ValueError`` 未知处置 / 队列项已关 / queue_type 不支持
    该处置 / state 级非法迁移(后者由 pg_io.transition 守卫,整事务回滚)。
    """
    if disposition not in DISPOSITION_TARGET:
        raise ValueError(f"未知处置: {disposition}")
    target = DISPOSITION_TARGET[disposition]

    with pg.session() as s:
        q = s.get(ReviewQueue, queue_id)
        if q is None:
            raise KeyError(queue_id)
        if q.status != "open":
            raise ValueError(f"队列项已处置: {queue_id}(status={q.status})")
        allowed = ALLOWED_DISPOSITIONS.get(q.queue_type, frozenset())
        if disposition not in allowed:
            raise ValueError(
                f"{q.queue_type} 不支持处置 {disposition}(允许: {sorted(allowed)})"
            )

        dvid = q.doc_version_id
        before = s.get(DocVersion, dvid).pipeline_status  # 迁移前态(transition 会就地改)
        # 迁移 + events(加入本事务):非法迁移在此抛 ValueError → 整事务回滚
        pg.transition(
            dvid,
            target,
            actor=operator,
            detail={"queue_id": queue_id, "disposition": disposition, "reason": reason},
            session=s,
        )
        s.add(
            RemediationRecord(
                doc_version_id=dvid,
                queue_id=queue_id,
                disposition=disposition,
                operator=operator,
                reason=reason,
                before_state=before,
                after_state=target.value,
            )
        )
        q.status = "closed"
        q.disposition = disposition
        q.operator = operator
        q.processed_at = datetime.now(UTC)

    return DispositionOutcome(queue_id, dvid, disposition, before, target.value)
