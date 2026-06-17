"""Stage 纯函数的统一契约:``StageContext`` 输入、``StageResult`` 输出、``QueueItem`` 入队。

约定(SPEC 边界):stage 为纯函数,只读 PG 状态 + ObjectStore 产物,返回新状态 + 产物;
**由 orchestrator 执行状态迁移并写 pipeline_events**,stage 自身不落库迁移。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pipeline.config import Settings
from pipeline.states import PipelineState


class QueueType(StrEnum):
    """统一审核队列的三类来源(review_queue.queue_type)。"""

    QC_FIX = "qc_fix"  # QC_FAILED / PARSE_FAILED
    QUARANTINE = "quarantine"  # S0 隔离
    META_CONFIRM = "meta_confirm"  # META_REVIEW + L1/manifest 冲突


@dataclass(frozen=True)
class QueueItem:
    """需人工处置时,stage 通过 StageResult 带出的入队请求。"""

    queue_type: QueueType
    doc_version_id: str
    reason: str = ""
    evidence: dict[str, Any] | None = None  # 失败指标 + 定位证据(写入 review_queue.evidence JSON)


@dataclass(frozen=True)
class StageContext:
    """stage 运行上下文。object_store / db 的具体类型在 A6/A7 接入(add-only)。"""

    config: Settings
    object_store: Any = None  # ObjectStore(A6)
    db: Any = None  # PgIO(A7)
    embedding: Any = None  # EmbeddingClient(C4),s5 嵌入用
    milvus: Any = None  # MilvusIO(C5,已 connect),s5 索引用
    user: str = "system"  # 操作者(写 pipeline_events.actor)


@dataclass
class StageResult:
    """stage 输出:目标状态 + 可选错误码/证据/入队/产物/边缘标记。"""

    next_state: PipelineState
    error_code: str | None = None  # 见 states.ErrorCode
    evidence: dict[str, Any] | None = None  # 失败指标 + 定位
    queue: QueueItem | None = None  # 需人工处置时入队
    artifacts: dict[str, str] = field(default_factory=dict)  # 产物 ObjectStore key 等
    marginal: bool = False  # QC 边缘通过带标记(qc_marginal)
