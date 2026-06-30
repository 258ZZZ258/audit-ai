"""单进程轮询 worker:推进可推进态文档,人工等待态不轮询。

设计(SPEC 边界):stage 为纯函数 ``(ctx, dvid) -> StageResult``,由本编排器执行状态迁移
并写 pipeline_events(经 pg_io.transition,内含 can_transition 守卫)。stage 经 ``stages``
注入(state → stage),B2+ 注册真实 stage,测试注入 fake。

只轮询 ``WORKER_ADVANCEABLE_STATES`` 中**且已注册 stage**的状态;人工等待态
(QC_FAILED / META_REVIEW / QUARANTINED / PARSE_FAILED)与终态结构上不会被取到。
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from ulid import ULID

from common.pg_models import DocVersion, ReviewQueue
from pipeline.index.pg_io import PgIO
from pipeline.stage_base import QueueItem, StageContext, StageResult
from pipeline.states import WORKER_ADVANCEABLE_STATES, PipelineState

logger = logging.getLogger(__name__)

Stage = Callable[[StageContext, str], StageResult]


class Orchestrator:
    def __init__(self, pg: PgIO, ctx: StageContext, stages: dict[PipelineState, Stage]) -> None:
        self.pg = pg
        self.ctx = ctx
        self.stages = stages

    def _advanceable(self) -> list[DocVersion]:
        states = [s for s in WORKER_ADVANCEABLE_STATES if s in self.stages]
        return self.pg.docs_in_states(states)

    def _queue_row(self, item: QueueItem) -> ReviewQueue:
        return ReviewQueue(
            queue_id=str(ULID()),
            queue_type=item.queue_type,
            doc_version_id=item.doc_version_id,
            reason=item.reason,
            evidence=item.evidence,
            status="open",
        )

    def _apply(self, dvid: str, result: StageResult) -> None:
        # 入队与迁移同一事务(pg_io.transition 内):非法迁移/DB 错误一并回滚,不留孤儿队列行。
        self.pg.transition(
            dvid,
            result.next_state,
            actor="system",
            error_code=result.error_code,
            detail=result.evidence,
            queue_row=self._queue_row(result.queue) if result.queue is not None else None,
        )

    def step(self, dv: DocVersion) -> bool:
        """推进一个文档一步;无对应 stage 返回 False。"""
        stage = self.stages.get(PipelineState(dv.pipeline_status))
        if stage is None:
            return False
        self._apply(dv.doc_version_id, stage(self.ctx, dv.doc_version_id))
        return True

    def run_until_idle(self, max_steps: int = 10000) -> int:
        """反复推进直至无可推进文档(或达 max_steps 安全上限)。返回总步数。

        单件 stage 抛异常 → 隔离:记录(log + 留原态,由调用方状态分布可见)+ 本轮排除该件,
        **不连累整批**。否则一个坏件(如 chunk_id 撞车)会让整批 ingest 崩、其余件全搁浅
        (B 模式批量驱动健壮性)。失败件留原态待下轮重试 / 人工处置,不静默成功失档。
        """
        steps = 0
        failed: set[str] = set()
        while steps < max_steps:
            docs = [d for d in self._advanceable() if d.doc_version_id not in failed]
            if not docs:
                break
            advanced = 0
            for dv in docs:
                try:
                    if self.step(dv):
                        advanced += 1
                except Exception as e:  # noqa: BLE001 单件失败隔离,不连累整批
                    failed.add(dv.doc_version_id)
                    logger.warning(
                        "推进 %s 在 %s 失败(隔离,留原态):%s",
                        dv.doc_version_id,
                        dv.pipeline_status,
                        e,
                    )
            steps += advanced
            if advanced == 0:
                break
        if failed:
            logger.warning("本批驱动隔离 %d 件失败(留原态,见上):%s", len(failed), sorted(failed))
        return steps
