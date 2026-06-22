"""§10 统一输出契约:后端只交付此 JSON,前端(genesis-ui)只消费(前端无关化)。

要点:四级引用由后端从 PG 回查填充(§7.3);``route_type`` 驱动前端差异化渲染(判定型带人工
复核框);``answer_blocks`` 经 ``stream`` 标记增量推送;``ai_label`` 强制存在(§9.3)。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum


class RouteType(StrEnum):
    """八路 route_type(§10 / §4.2)。"""

    EVIDENCE = "evidence"          # R1 依据查询
    CHANGE = "change"             # R2 变更查询
    CASE = "case"                 # R3 相似案例
    ENUMERATE = "enumerate"       # R4 多文档列举
    JUDGMENTAL = "judgmental"     # R5 判定型
    STATISTICAL = "statistical"   # R6 统计型
    CLARIFY = "clarify"           # R7 需澄清
    REFUSE = "refuse"             # R8 兜底 / 覆盖感知拒答


class BlockType(StrEnum):
    """answer_blocks 的块类型(§10)。"""

    TEXT = "text"
    TABLE = "table"
    CASE_CARD = "case_card"
    CLARIFY_QUESTION = "clarify_question"


@dataclass
class AnswerBlock:
    type: BlockType
    content: str
    stream: bool = True

    def to_dict(self) -> dict:
        return {"type": self.type.value, "content": self.content, "stream": self.stream}


@dataclass
class Citation:
    """四级引用锚点(§7.3):clause_id → 文档(标题/文号/版本) → 条款路径 → 页码 → 状态。

    一律由后端从 PG ``chunks``/``doc_versions`` 回查填充,不用 Milvus 截断文本。
    """

    clause_id: str
    doc_title: str | None = None
    doc_no: str | None = None
    clause_path: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    version: str | None = None
    status: str | None = None  # effective | superseded | abolished

    def to_dict(self) -> dict:
        return {
            "clause_id": self.clause_id,
            "doc_title": self.doc_title,
            "doc_no": self.doc_no,
            "clause_path": self.clause_path,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "version": self.version,
            "status": self.status,
        }


@dataclass
class QueryResult:
    """§10 契约根对象。``to_dict``/``to_json`` 产出前端消费的稳定 JSON 形状。"""

    route_type: RouteType
    answer_blocks: list[AnswerBlock] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    confidence: float = 0.0
    ai_label: bool = True             # AI 内容标识:强制存在(§9.3)
    review_required: bool = False     # R5 判定型 = true,前端渲染人工复核框
    exhausted_scope: list[str] = field(default_factory=list)  # 覆盖感知拒答时填(§8.2)
    export_enabled: bool = True

    def to_dict(self) -> dict:
        return {
            "route_type": self.route_type.value,
            "answer_blocks": [b.to_dict() for b in self.answer_blocks],
            "citations": [c.to_dict() for c in self.citations],
            "confidence": self.confidence,
            "ai_label": self.ai_label,
            "review_required": self.review_required,
            "exhausted_scope": list(self.exhausted_scope),
            "export_enabled": self.export_enabled,
        }

    def to_json(self, *, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)
