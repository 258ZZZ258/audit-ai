"""单进程轮询 worker:推进可推进态文档,人工等待态不轮询。

设计(SPEC 边界):stage 为纯函数 ``(ctx, dvid) -> StageResult``,由本编排器执行状态迁移
并写 pipeline_events(经 pg_io.transition,内含 can_transition 守卫)。stage 经 ``stages``
注入(state → stage),B2+ 注册真实 stage,测试注入 fake。

只轮询 ``WORKER_ADVANCEABLE_STATES`` 中**且已注册 stage**的状态;人工等待态
(QC_FAILED / META_REVIEW / QUARANTINED / PARSE_FAILED)与终态结构上不会被取到。
"""

from __future__ import annotations

from collections.abc import Callable

from ulid import ULID

from pipeline.index.pg_io import PgIO
from pipeline.index.pg_models import DocVersion, ReviewQueue
from pipeline.stage_base import QueueItem, StageContext, StageResult
from pipeline.states import WORKER_ADVANCEABLE_STATES, PipelineState

Stage = Callable[[StageContext, str], StageResult]


class Orchestrator:
    def __init__(self, pg: PgIO, ctx: StageContext, stages: dict[PipelineState, Stage]) -> None:
        self.pg = pg
        self.ctx = ctx
        self.stages = stages

    def _advanceable(self) -> list[DocVersion]:
        states = [s for s in WORKER_ADVANCEABLE_STATES if s in self.stages]
        return self.pg.docs_in_states(states)

    def _enqueue(self, item: QueueItem) -> None:
        with self.pg.session() as s:
            s.add(
                ReviewQueue(
                    queue_id=str(ULID()),
                    queue_type=item.queue_type,
                    doc_version_id=item.doc_version_id,
                    reason=item.reason,
                    evidence=item.evidence,
                    status="open",
                )
            )

    def _apply(self, dvid: str, result: StageResult) -> None:
        if result.queue is not None:
            self._enqueue(result.queue)
        self.pg.transition(
            dvid,
            result.next_state,
            actor="system",
            error_code=result.error_code,
            detail=result.evidence,
        )

    def step(self, dv: DocVersion) -> bool:
        """推进一个文档一步;无对应 stage 返回 False。"""
        stage = self.stages.get(PipelineState(dv.pipeline_status))
        if stage is None:
            return False
        self._apply(dv.doc_version_id, stage(self.ctx, dv.doc_version_id))
        return True

    def run_until_idle(self, max_steps: int = 10000) -> int:
        """反复推进直至无可推进文档(或达 max_steps 安全上限)。返回总步数。"""
        steps = 0
        while steps < max_steps:
            docs = self._advanceable()
            if not docs:
                break
            advanced = sum(int(self.step(dv)) for dv in docs)
            steps += advanced
            if advanced == 0:
                break
        return steps
