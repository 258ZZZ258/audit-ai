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


def _compact(**kv) -> dict:
    """丢弃值为 ``None`` 的键(可选字段缺失即省略,零臆造;承 ``case_card.CaseCard`` 先例)。

    空列表省略:调用处传 ``field or None``(空 → None → 丢弃)。必填字段非 None 恒保留。
    """
    return {k: v for k, v in kv.items() if v is not None}


@dataclass
class RegulationHit:
    """命中制度(SPEC-API §4.1)。日期为 ISO 串(装配层 ``date.isoformat()``);可选缺失省略。"""

    seq: int
    doc_id: str
    doc_version_id: str
    title: str
    match_score: float                 # 候选集内融合分 min-max 归一 → 0–1(前端直显 %)
    clause_excerpt: str
    doc_no: str | None = None
    publish_date: str | None = None    # 发布日期 ISO
    effective_date: str | None = None  # 生效日期 ISO
    issuing_dept: str | None = None    # 发布部门(doc_versions.issuer)
    version: str | None = None
    status: str | None = None          # effective | superseded | abolished

    def to_dict(self) -> dict:
        return _compact(
            seq=self.seq, doc_id=self.doc_id, doc_version_id=self.doc_version_id,
            title=self.title, match_score=self.match_score, clause_excerpt=self.clause_excerpt,
            doc_no=self.doc_no, publish_date=self.publish_date,
            effective_date=self.effective_date, issuing_dept=self.issuing_dept,
            version=self.version, status=self.status,
        )


@dataclass
class ClauseHit:
    """命中条款(SPEC-API §4.2)。``theme``/``summary`` 为 ⚠-data/⚠-model,缺省省略。"""

    seq: int
    clause_id: str
    clause_title: str
    doc_title: str
    doc_id: str
    match_score: float
    clause_path: str | None = None
    summary: str | None = None
    theme: str | None = None

    def to_dict(self) -> dict:
        return _compact(
            seq=self.seq, clause_id=self.clause_id, clause_title=self.clause_title,
            doc_title=self.doc_title, doc_id=self.doc_id, match_score=self.match_score,
            clause_path=self.clause_path, summary=self.summary, theme=self.theme,
        )


@dataclass
class RegulatoryRuleHit:
    """监管规则(外规,SPEC-API §4.3)。``related_internal`` 依赖 clause_references,空则省略。"""

    seq: int
    clause_id: str
    doc_id: str
    title: str
    core_requirement: str
    issuing_body: str | None = None
    doc_no: str | None = None          # 文号
    publish_date: str | None = None
    theme: str | None = None
    related_internal: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return _compact(
            seq=self.seq, clause_id=self.clause_id, doc_id=self.doc_id, title=self.title,
            core_requirement=self.core_requirement, issuing_body=self.issuing_body,
            doc_no=self.doc_no, publish_date=self.publish_date, theme=self.theme,
            related_internal=self.related_internal or None,
        )


@dataclass
class CaseHit:
    """相关案例(SPEC-API §4.4)。要素逐字来自 PG ``cases``;L2/LLM 字段缺失省略(零臆造)。"""

    seq: int
    case_id: str
    doc_version_id: str
    title: str
    regulator: str | None = None       # 监管机构(cases.penalty_org)
    penalty_date: str | None = None    # 处罚日期 ISO
    violation_theme: str | None = None  # 违规主题(cases.violation_category,L2)
    core_issue: str | None = None      # 核心问题(LLM 提炼,默认关 → None)
    insight: str | None = None         # 启示要点(LLM 提炼,默认关 → None)
    related_regulations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return _compact(
            seq=self.seq, case_id=self.case_id, doc_version_id=self.doc_version_id,
            title=self.title, regulator=self.regulator, penalty_date=self.penalty_date,
            violation_theme=self.violation_theme, core_issue=self.core_issue,
            insight=self.insight, related_regulations=self.related_regulations or None,
        )


@dataclass
class DigestCard:
    """提炼卡片(监管要求提炼 / 案例启示摘要,SPEC-API §4.5)。仅在有内容时构造。"""

    tag: str
    title: str
    body: str

    def to_dict(self) -> dict:
        return {"tag": self.tag, "title": self.title, "body": self.body}


@dataclass
class TabPayload:
    """一个 Tab 的载荷:``total``(计数,驱动「命中制度(3)」)+ ``items``(命中项列表)。

    ``total`` 缺省 = ``len(items)``;截断/分页时可显式给(≠ len)。
    """

    items: list = field(default_factory=list)
    total: int | None = None

    @property
    def count(self) -> int:
        """计数(驱动「命中制度(3)」):显式 total 优先,否则 len(items)。"""
        return self.total if self.total is not None else len(self.items)

    def to_dict(self) -> dict:
        return {"total": self.count, "items": [i.to_dict() for i in self.items]}


@dataclass
class StructuredResult:
    """结构化四-Tab 结果(SPEC-API §4)。API 边界层装配,不进 graph 域节点。

    四 Tab 恒在(空则 total=0);``citation_advice``/``regulatory_digest``/``case_insights``
    为 ⚠-model(LLM 提炼开关默认关 → 空列表,前端隐藏)。
    """

    regulations: TabPayload         # 命中制度
    clauses: TabPayload             # 命中条款
    regulatory_rules: TabPayload    # 监管规则
    cases: TabPayload               # 相关案例
    citation_advice: list[str] = field(default_factory=list)
    regulatory_digest: list[DigestCard] = field(default_factory=list)
    case_insights: list[DigestCard] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "regulations": self.regulations.to_dict(),
            "clauses": self.clauses.to_dict(),
            "regulatory_rules": self.regulatory_rules.to_dict(),
            "cases": self.cases.to_dict(),
            "citation_advice": list(self.citation_advice),
            "regulatory_digest": [c.to_dict() for c in self.regulatory_digest],
            "case_insights": [c.to_dict() for c in self.case_insights],
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
    # ── SPEC-API 加法(默认时 to_dict 省略 → §10 byte 等价,CLI 输出不变)──
    structured: StructuredResult | None = None  # 四-Tab(API 层装配;CLI/域默认 None)
    meta: dict = field(default_factory=dict)     # {elapsed_ms, total_hits, hit_counts}(API 层填)

    def to_dict(self) -> dict:
        d = {
            "route_type": self.route_type.value,
            "answer_blocks": [b.to_dict() for b in self.answer_blocks],
            "citations": [c.to_dict() for c in self.citations],
            "confidence": self.confidence,
            "ai_label": self.ai_label,
            "review_required": self.review_required,
            "exhausted_scope": list(self.exhausted_scope),
            "export_enabled": self.export_enabled,
        }
        # 缺省省略:structured=None 且 meta={} 时不加键 → 与既有 8 键契约 byte 等价
        if self.structured is not None:
            d["structured"] = self.structured.to_dict()
        if self.meta:
            d["meta"] = dict(self.meta)
        return d

    def to_json(self, *, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)
