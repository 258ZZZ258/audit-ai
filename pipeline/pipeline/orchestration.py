"""编排接缝(WorkflowEngine):demo = 单进程 PG 轮询(StateMachineWorkflow);生产 = Temporal。

§11 生产用 Temporal(人工关卡走 Signal、continue-as-new 防历史膨胀、解析/OCR/嵌入独立 task queue
水平扩展);demo 用单进程轮询 worker(``Orchestrator``)作 PG 状态机驱动的等价替身。本接缝让二者
经配置(``PIPELINE_WORKFLOW_BACKEND``,默认 state_machine)切换;生产实现本次留 stub。
"""

from __future__ import annotations

import os
from typing import Protocol, runtime_checkable

from common.pg_models import DocVersion
from pipeline.index.pg_io import PgIO
from pipeline.orchestrator import Orchestrator, Stage
from pipeline.stage_base import StageContext
from pipeline.states import PipelineState


@runtime_checkable
class WorkflowEngine(Protocol):
    """编排引擎抽象:推进可推进态文档到各自停态。consumer(cli)只依赖这两个方法。"""

    def step(self, dv: DocVersion) -> bool: ...

    def run_until_idle(self, max_steps: int = 10000) -> int: ...


#: demo 默认实现(单进程 PG 轮询 = Temporal 状态机替身);Orchestrator 即 WorkflowEngine 实现。
StateMachineWorkflow = Orchestrator


class TemporalWorkflow:
    """生产编排实现占位(§11):Temporal workflow + Signal 人工关卡 + continue-as-new + 多 task queue。

    **再集成触发条件**:信创内网 Temporal 可部署性验证通过(集群可落地 + Signal 挂起/续跑语义验证),
    且需要「人工关卡 Signal 建模 / 解析池水平扩展 / 断点精确续跑」任一能力时,以本类替换 stub。
    届时 Activity 直接复用现有纯函数 stage —— 确定性 chunk_id + upsert 幂等
    已满足 Activity 幂等要求。
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError(
            "TemporalWorkflow 未实现(生产编排,属未来 CP)。再集成触发:信创内网 Temporal 可部署性"
            "验证通过。当前请用 PIPELINE_WORKFLOW_BACKEND=state_machine(默认)。"
        )


def make_workflow_engine(
    pg: PgIO, ctx: StageContext, stages: dict[PipelineState, Stage]
) -> WorkflowEngine:
    """按 ``PIPELINE_WORKFLOW_BACKEND``(默认 ``state_machine``)返回编排引擎实现(默认 = demo)。"""
    backend = os.environ.get("PIPELINE_WORKFLOW_BACKEND", "state_machine")
    if backend == "state_machine":
        return StateMachineWorkflow(pg, ctx, stages)
    if backend == "temporal":
        return TemporalWorkflow(pg, ctx, stages)
    raise ValueError(f"未知 PIPELINE_WORKFLOW_BACKEND: {backend!r}(state_machine | temporal)")
