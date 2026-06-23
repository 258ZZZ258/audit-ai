"""§6.3 案例卡片组装(纯函数):``cases`` 行 + ``doc_versions`` 元数据 → ``CASE_CARD`` 块。

红线:要素**逐字来自 PG 权威**(``cases`` L1 字段 + ``doc_versions`` 标题),**不来自 Milvus 截断文本 /
不来自 LLM**;**缺失字段省略、零臆造**——尤其 L2 字段(``violation_category`` / ``cited_regulations``)
默认空时不进卡片(SPEC-R3 §0/§8)。``content`` 承载结构化 JSON 字符串(SPEC-R3 §9-Q4),前端解析渲染。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from query.contract import AnswerBlock, BlockType


@dataclass(frozen=True)
class CaseCard:
    """一案一卡的结构化要素(只承载 PG 已落字段;缺失留 None/[],组卡时省略)。"""

    doc_version_id: str
    title: str | None = None                 # doc_versions 权威标题
    penalty_org: str | None = None           # 处罚机构(L1)
    penalty_date: str | None = None          # 处罚日期 ISO(L1)
    respondent: str | None = None            # 当事人(L1)
    penalty_type: str | None = None          # 处罚类型(L1)
    amount_wan: float | None = None          # 金额万元(L1)
    violation_category: str | None = None    # 违规事由(L2,默认空)
    cited_regulations: list[str] = field(default_factory=list)  # 引用外规条款(L2,默认空)

    @classmethod
    def from_rows(cls, case_row, doc_meta) -> CaseCard:
        """``case_row``=``cases`` 行;``doc_meta``=``doc_versions`` 行(可 None,标题则省略)。"""
        pd = getattr(case_row, "penalty_date", None)
        return cls(
            doc_version_id=case_row.doc_version_id,
            title=getattr(doc_meta, "title", None) if doc_meta is not None else None,
            penalty_org=getattr(case_row, "penalty_org", None),
            penalty_date=pd.isoformat() if pd is not None else None,
            respondent=getattr(case_row, "respondent", None),
            penalty_type=getattr(case_row, "penalty_type", None),
            amount_wan=getattr(case_row, "amount_wan", None),
            violation_category=getattr(case_row, "violation_category", None),
            cited_regulations=list(getattr(case_row, "cited_regulations", None) or []),
        )

    def to_content(self) -> dict:
        """缺失字段省略(零臆造);``doc_version_id`` 身份恒在。"""
        d: dict = {"doc_version_id": self.doc_version_id}
        if self.title:
            d["title"] = self.title
        if self.penalty_org:
            d["penalty_org"] = self.penalty_org
        if self.penalty_date:
            d["penalty_date"] = self.penalty_date
        if self.respondent:
            d["respondent"] = self.respondent
        if self.penalty_type:
            d["penalty_type"] = self.penalty_type
        if self.amount_wan is not None:
            d["amount_wan"] = self.amount_wan
        if self.violation_category:
            d["violation_category"] = self.violation_category
        if self.cited_regulations:
            d["cited_regulations"] = self.cited_regulations
        return d


def build_case_card(case_row, doc_meta) -> AnswerBlock:
    """``cases`` 行 + ``doc_versions`` 元数据 → ``CASE_CARD`` 块(content=JSON 字符串)。

    结构化卡片为**原子块**(``stream=False``),前端整体渲染、不逐 token 流式。
    """
    content = json.dumps(CaseCard.from_rows(case_row, doc_meta).to_content(), ensure_ascii=False)
    return AnswerBlock(BlockType.CASE_CARD, content, stream=False)
