"""文档级状态机(demo 子集)+ 合法迁移表 + 错误码体系。

状态枚举为生产子集:去掉 REPARSE_PENDING/REPARSING —— 由 ``reprocess`` 命令直接重置回
REGISTERED 全量重跑覆盖(确定性 chunk_id 使重跑天然安全)。

三类状态划分(并覆盖全部成员):
- TERMINAL:终态,无后继。
- HUMAN_WAIT:人工等待态,orchestrator **不轮询**,等 CLI 推进。
- WORKER_ADVANCEABLE:worker 轮询并调用对应 stage 推进。
"""

from __future__ import annotations

from enum import StrEnum


class PipelineState(StrEnum):
    REGISTERED = "REGISTERED"
    PARSING = "PARSING"
    PARSE_FAILED = "PARSE_FAILED"
    QC_PENDING = "QC_PENDING"
    QC_FAILED = "QC_FAILED"
    STRUCTURING = "STRUCTURING"
    META_REVIEW = "META_REVIEW"
    EMBEDDING = "EMBEDDING"
    INDEXING = "INDEXING"
    INDEXED = "INDEXED"
    DEGRADED_INDEXED = "DEGRADED_INDEXED"
    REJECTED = "REJECTED"
    QUARANTINED = "QUARANTINED"


_PS = PipelineState

#: 正常前进 + 补录/隔离处置的合法迁移(reprocess 重置另见 ``REPROCESS_RESET_FROM``)。
ALLOWED_TRANSITIONS: dict[PipelineState, frozenset[PipelineState]] = {
    _PS.REGISTERED: frozenset({_PS.PARSING, _PS.QUARANTINED}),
    _PS.PARSING: frozenset({_PS.QC_PENDING, _PS.PARSE_FAILED, _PS.QUARANTINED}),
    _PS.PARSE_FAILED: frozenset({_PS.QC_PENDING, _PS.REJECTED}),  # queue fix(补 IR 重入)/ reject
    _PS.QC_PENDING: frozenset({_PS.STRUCTURING, _PS.QC_FAILED}),
    # QC_FAILED:fix→QC_PENDING / degrade→STRUCTURING(置 degraded)/ reject(直达 DEGRADED 边保留备用)
    _PS.QC_FAILED: frozenset({_PS.QC_PENDING, _PS.STRUCTURING, _PS.DEGRADED_INDEXED, _PS.REJECTED}),
    # s3+s4 自动推进;无冲突元数据可由配置直接放行至 EMBEDDING。
    _PS.STRUCTURING: frozenset({_PS.META_REVIEW, _PS.EMBEDDING}),
    _PS.META_REVIEW: frozenset({_PS.EMBEDDING, _PS.REJECTED}),  # CLI approve / reject
    _PS.EMBEDDING: frozenset({_PS.INDEXING}),
    _PS.INDEXING: frozenset({_PS.INDEXED, _PS.DEGRADED_INDEXED}),  # degraded → DEGRADED_INDEXED
    _PS.INDEXED: frozenset(),
    _PS.DEGRADED_INDEXED: frozenset(),
    _PS.REJECTED: frozenset(),
    _PS.QUARANTINED: frozenset({_PS.PARSING, _PS.REJECTED}),  # release 重入解析 / reject
}

#: reprocess 可从这些状态重置回 REGISTERED(全量重跑 + 按 doc_version_id 清孤儿)。
REPROCESS_RESET_FROM: frozenset[PipelineState] = frozenset(
    {
        _PS.INDEXED,
        _PS.DEGRADED_INDEXED,
        _PS.REJECTED,
        _PS.PARSE_FAILED,
        _PS.QC_FAILED,
        _PS.QUARANTINED,
    }
)

TERMINAL_STATES: frozenset[PipelineState] = frozenset(
    {_PS.INDEXED, _PS.DEGRADED_INDEXED, _PS.REJECTED}
)

#: 人工等待态:orchestrator 不轮询,等 CLI(queue/meta)推进。
HUMAN_WAIT_STATES: frozenset[PipelineState] = frozenset(
    {_PS.PARSE_FAILED, _PS.QC_FAILED, _PS.META_REVIEW, _PS.QUARANTINED}
)

#: worker 轮询并自动推进的状态。
WORKER_ADVANCEABLE_STATES: frozenset[PipelineState] = frozenset(
    {_PS.REGISTERED, _PS.PARSING, _PS.QC_PENDING, _PS.STRUCTURING, _PS.EMBEDDING, _PS.INDEXING}
)


def can_transition(frm: PipelineState, to: PipelineState) -> bool:
    """是否允许从 ``frm`` 迁移到 ``to``(含 reprocess 重置回 REGISTERED)。"""
    if to in ALLOWED_TRANSITIONS.get(frm, frozenset()):
        return True
    return to is _PS.REGISTERED and frm in REPROCESS_RESET_FROM


class ErrorCode(StrEnum):
    """生产 §11.2 错误码体系的 M1 实际触达子集;demo 专属码带 ``-DEMO`` 后缀。"""

    # E1xx 接入/格式
    FORMAT_NOT_WHITELISTED = "E101-DEMO"  # 白名单外格式(demo 仅 docx/pdf)
    # E2xx 解析
    SCANNED_OCR_DISABLED = "E202-DEMO"  # 扫描件,OCR 未启用 → 隔离
    PARSE_TIMEOUT = "E203"  # 单文档解析超时
    RENDITION_FAILED = "E204-DEMO"  # 规范渲染件(soffice)生成失败
    OCR_FAILED = "E205-DEMO"  # OCR 解析失败(MinerU 未装 / 解析异常)
    # E3xx 质检
    QC_GATE_FAILED = "E301"  # 质检硬关卡未通过
    # E7xx 对账(M2 触达)
    RECONCILE_MISMATCH = "E701"  # PG/Milvus 数不平
    # E8xx 评测(M2 触达)
    SMOKE_NO_HIT = "E801"  # T2 冒烟未命中
    SMOKE_FILTER_MISSING = "E802"  # T2 status 过滤缺失
