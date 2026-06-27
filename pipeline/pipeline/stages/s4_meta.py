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

import logging
from dataclasses import asdict
from datetime import date

from common.ir import BlockType, IRDocument
from common.pg_models import Document, DocVersion
from pipeline.llm_client import make_llm_client
from pipeline.meta import case_extract, case_l2, l1_rules, l2_llm
from pipeline.stage_base import QueueItem, QueueType, StageContext, StageResult
from pipeline.states import PipelineState

logger = logging.getLogger(__name__)

#: 业务域 L2 喂模型的文档文本上限(字符):整篇过长 → 截断控 token(判业务域用篇首足矣)。
_BIZ_TEXT_MAX = 4000


def run(ctx: StageContext, doc_version_id: str) -> StageResult:
    ir = ctx.object_store.load_ir(doc_version_id)
    dv = ctx.db.get(DocVersion, doc_version_id)
    issuers = [(i.code, i.name) for i in ctx.db.get_issuers()]

    # P-CASE:在常规 L1 路径之外,额外抽案例要素 upsert 到 cases 表(P-INT/P-EXT/P-QA 不受影响)。
    doc = ctx.db.get(Document, dv.logical_id) if dv else None
    if doc and doc.corpus_type == "P-CASE":
        _extract_case(ctx, dv, ir)

    meta = l1_rules.extract(ir, issuers)
    conflicts = l1_rules.cross_check(
        meta,
        doc_number=dv.doc_number,
        issue_date=dv.issue_date,
        issuer_code=l1_rules.resolve_issuer(dv.issuer, issuers),
        title=dv.title,
    )

    # T2.3 业务域 L2(l2_enabled,默认关):写 doc_versions.biz_domains/source(非阻断);
    # P-INT 候选 / manifest 冲突 / 直落 profile 抽中 → biz_review(入 META_REVIEW)。
    biz_l2 = _safe_biz_l2(ctx, dv, ir, doc) if ctx.config.toggles.l2_enabled else None
    biz_review = bool(biz_l2 and biz_l2["needs_review"])

    evidence = {"conflicts": [asdict(c) for c in conflicts]}
    if biz_l2:
        evidence["biz_l2"] = biz_l2
    # B-严:无冲突**且非修订件**才自动放行;修订件(带 supersedes)即便无冲突仍入闸,
    # 因 finalize 会 supersede 旧版——这一最有后果的权威变更须有人点头(见 devlog 双模式)。
    # 业务域 L2 待确认(biz_review)同样阻自动放行(内规候选/冲突须人工担责)。
    if (
        not conflicts
        and not biz_review
        and ctx.config.toggles.auto_confirm_meta_no_conflict
        and not dv.supersedes_version_id
    ):
        return StageResult(
            next_state=PipelineState.EMBEDDING,
            evidence={**evidence, "auto_confirmed": True},
        )

    # 入 meta_confirm 队列。reason 标明触发缘由(冲突 / 业务域 L2 / 修订 / 常规),便于 queue 区分。
    if conflicts:
        reason = "L1/manifest 元数据冲突"
    elif biz_review:
        reason = "业务域 L2 待人工确认(P-INT 候选 / manifest 冲突 / 抽检)"
    elif dv.supersedes_version_id:
        reason = "修订件待人工确认(无冲突,supersede 旧版需放行)"
    else:
        reason = "元数据待人工确认(无冲突)"
    return StageResult(
        next_state=PipelineState.META_REVIEW,
        evidence=evidence,
        queue=QueueItem(QueueType.META_CONFIRM, doc_version_id, reason, evidence),
    )


def _ir_text(ir: IRDocument) -> str:
    """决定书全文(标题 + 各文本块,按文档序拼接;表格块跳过)供案例要素抽取。"""
    parts = [ir.title or ""]
    parts += [b.text for b in ir.blocks if b.type is not BlockType.TABLE and b.text.strip()]
    return "\n".join(p for p in parts if p)


def _extract_case(ctx: StageContext, dv: DocVersion, ir: IRDocument) -> None:
    """规则抽案例要素 → upsert cases 行;``case_l2_enabled`` 时叠加 L2(引用外规对齐 + 违规事由)。

    penalty_date ISO 字符串转 date;manifest issuer 作处罚机构兜底。L2 富集非阻断
    (``case_l2.apply`` 内吞异常),失败保留 L1 占位
    (``cited_regulations=[]`` / ``violation_category=None``)。
    """
    case_text = _ir_text(ir)
    fields = case_extract.extract_case(case_text, {"issuer": dv.issuer})
    pdate = fields.pop("penalty_date")
    fields["penalty_date"] = date.fromisoformat(pdate) if pdate else None
    if ctx.config.toggles.case_l2_enabled:  # 默认关 → 零 LLM(不构造 client、不触达本路径)
        case_l2.apply(ctx, case_text, fields)
    ctx.db.upsert_case(dv.doc_version_id, fields)


def _safe_biz_l2(
    ctx: StageContext, dv: DocVersion, ir: IRDocument, doc: Document | None
) -> dict | None:
    """跑业务域 L2,**非阻断**:LLM / 任何异常吞掉记日志,返回 None(不写、不复核)。"""
    try:
        return _apply_biz_l2(ctx, dv, ir, doc)
    except Exception as e:  # noqa: BLE001 L2 富集失败不阻断管线(同 E2/case_l2 纪律)
        logger.warning("业务域 L2 打标(%s)失败(不阻断):%s", dv.doc_version_id, e)
        return None


def _apply_biz_l2(
    ctx: StageContext, dv: DocVersion, ir: IRDocument, doc: Document | None
) -> dict | None:
    """LLM 打业务域 → 字典裁剪 → profile 分档定 (biz_domains, source, review);写权威字段。

    返回 ``{needs_review, biz_domains, source}``;无候选(manifest 空且 LLM 空)→ None(不写)。
    """
    corpus = (doc.corpus_type if doc else "") or ""
    allowed = [d.name for d in ctx.db.get_biz_domains()]
    client = make_llm_client(ctx.config.llm.model)
    llm_biz = l2_llm.tag_biz_domain(client, _ir_text(ir)[:_BIZ_TEXT_MAX], allowed)
    manifest_biz = (dv.biz_domain or "").strip() or None
    prof = ctx.config.profiles.get(corpus)
    rate = prof.sampling_rate if prof else 0.0
    biz, source, review = l2_llm.biz_l2_decision(
        corpus, manifest_biz, llm_biz, sampling_rate=rate, sample_key=dv.doc_version_id
    )
    if biz is None:
        return None
    ctx.db.set_biz_domains(dv.doc_version_id, biz, source)
    return {"needs_review": review, "biz_domains": biz, "source": source}
