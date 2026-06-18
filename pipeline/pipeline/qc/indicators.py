"""S2 质检七指标(SPEC §6-S2;阈值从 config,全部 ⚠)。每个指标返回 IndicatorResult。

边缘通过带:落 [阈值, 阈值+ε](≥型)或 [阈值-ε, 阈值](≤型)→ marginal(仅标记不拦)。
整数型(条号连续性/层级)无边缘带:value 必须 =0。
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from common.ir import BlockType, IRDocument
from pipeline.chunking.clause_tree import (
    NodeType,
    build_tree,
    iter_articles,
)
from pipeline.chunking.normalize import strip_ws, to_halfwidth
from pipeline.chunking.qa_chunker import detect_qa_pairs
from pipeline.config import QcThresholds

_LOOSE_ARTICLE = re.compile(r"^第[〇零一二三四五六七八九十百千两\dA-Za-z.]+条")


@dataclass
class IndicatorResult:
    key: str
    index: int
    name: str
    value: float
    threshold: float
    passed: bool
    marginal: bool = False
    evidence: dict = field(default_factory=dict)


def _ge(value: float, threshold: float, eps: float) -> tuple[bool, bool]:
    passed = value >= threshold
    return passed, passed and value <= threshold + eps


def _le(value: float, threshold: float, eps: float) -> tuple[bool, bool]:
    passed = value <= threshold
    return passed, passed and value >= threshold - eps


def _base(num: str) -> int:
    """条号首段整数:``"17"``→17、插入条 ``"4-1"``→4、小数体例 ``"10.1.3"``→10(章级)。

    用于条号连续性:第X条 体例按条号查缺口;小数体例首段=章号,退化为「章是否齐全」。
    """
    return int(num.replace("-", ".").split(".")[0])


def _key(num: str) -> tuple[int, ...]:
    """条号排序键(变长整数元组):``"17"``→(17,)、插入条 ``"4-1"``→(4,1)、小数 ``"10.1.3"``→(10,1,3)。

    用于层级合法性的严格递增判定。元组比较天然处理:插入条 (4,1)>(4,) 不误判;小数跨节
    (10,2,5)>(10,1,3) 正确(即便节点未被识别为父级);真重复/逆序((4,)<=(4,) / (3,)<=(5,))仍被抓。
    """
    return tuple(int(x) for x in num.replace("-", ".").split("."))


def clause_coverage(ir: IRDocument, th: QcThresholds) -> IndicatorResult:
    structured = len(iter_articles(build_tree(ir.blocks)))
    loose = sum(1 for b in ir.blocks if _LOOSE_ARTICLE.match(strip_ws(to_halfwidth(b.text))))
    value = structured / loose if loose else 1.0
    passed, marginal = _ge(value, th.clause_coverage_min, th.edge_band_epsilon)
    return IndicatorResult(
        "clause_coverage", 1, "条款覆盖率", value, th.clause_coverage_min, passed, marginal,
        {"structured": structured, "scanned": loose},
    )


def clause_continuity(ir: IRDocument, th: QcThresholds) -> IndicatorResult:
    arts = iter_articles(build_tree(ir.blocks))
    bases = sorted({_base(a.number) for a in arts if a.number})
    gaps = [n for n in range(bases[0], bases[-1] + 1) if n not in bases] if bases else []
    hint = ""
    if gaps:
        page_by_idx = {b.index: b.page for b in ir.blocks}
        before = next((a for a in arts if a.number and _base(a.number) == gaps[0] - 1), None)
        page = page_by_idx.get(before.block_index) if before else None
        hint = f"第{gaps[0] - 1}条后缺第{gaps[0]}条" + (f"(第{page}页)" if page else "")
    passed = len(gaps) <= th.clause_continuity_max_gap
    return IndicatorResult(
        "clause_continuity", 2, "条号连续性", float(len(gaps)),
        float(th.clause_continuity_max_gap), passed, False, {"missing": gaps[:20], "hint": hint},
    )


def hierarchy_legality(ir: IRDocument, th: QcThresholds) -> IndicatorResult:
    root = build_tree(ir.blocks)
    violations: list[str] = []
    structural = {NodeType.CHAPTER, NodeType.SECTION, NodeType.ARTICLE}

    def walk(node) -> None:
        last: dict = {}
        for c in node.children:
            if c.type in structural and c.number:
                k = _key(c.number)  # (base, sub):插入条 (N,1) > 前条 (N,0),不误判
                if c.type in last and k <= last[c.type]:
                    violations.append(c.raw_label)
                last[c.type] = k
            walk(c)

    walk(root)
    passed = len(violations) <= th.hierarchy_illegal_max
    return IndicatorResult(
        "hierarchy_legality", 3, "层级合法性", float(len(violations)),
        float(th.hierarchy_illegal_max), passed, False, {"violations": violations[:20]},
    )


def page_anchor_complete(ir: IRDocument, th: QcThresholds) -> IndicatorResult:
    # 仅文本块需页码锚点;表格块页码另路(docx 无法对齐空文本表格)
    blocks = [b for b in ir.blocks if b.type is not BlockType.TABLE]
    with_page = sum(1 for b in blocks if b.page is not None)
    value = with_page / len(blocks) if blocks else 1.0
    passed, _ = _ge(value, th.page_anchor_complete_min, th.edge_band_epsilon)
    nulls = [b.index for b in blocks if b.page is None][:20]
    return IndicatorResult(
        "page_anchor_complete", 4, "页码锚点完整率", value, th.page_anchor_complete_min,
        passed, False,  # 阈值=100% 二元,无边缘带
        {"null_block_indices": nulls, "with_page": with_page, "total": len(blocks)},
    )


def table_consistency(ir: IRDocument, th: QcThresholds) -> IndicatorResult:
    tables = [b.table for b in ir.blocks if b.type is BlockType.TABLE and b.table]
    if not tables:
        value = 0.0
    else:
        empty = sum(
            1 for t in tables if t.n_rows == 0 or all(not c.text.strip() for c in t.cells)
        )
        value = empty / len(tables)
    passed, marginal = _le(value, th.table_empty_max, th.edge_band_epsilon)
    return IndicatorResult(
        "table_consistency", 5, "表格一致性", value, th.table_empty_max, passed, marginal,
        {"tables": len(tables)},
    )


def text_quality(ir: IRDocument, th: QcThresholds) -> IndicatorResult:
    total = garbled = 0
    for b in ir.blocks:
        if b.type is BlockType.TABLE:
            continue
        for ch in b.text:
            if ch.isspace():
                continue
            total += 1
            if ch == "�" or (ord(ch) < 0x20 and ch not in "\t\n"):
                garbled += 1
    value = garbled / total if total else 0.0
    passed, _ = _le(value, th.text_garbled_max, th.edge_band_epsilon)  # 阈值<ε 退化,关边缘带
    return IndicatorResult(
        "text_quality", 6, "文本质量", value, th.text_garbled_max, passed, False,
        {"garbled": garbled, "total": total},
    )


def extraction_sufficiency(ir: IRDocument, th: QcThresholds) -> IndicatorResult:
    per_page: Counter = Counter()
    for b in ir.blocks:
        if b.page:
            per_page[b.page] += len(strip_ws(b.text))
    pages = ir.page_count or (max(per_page) if per_page else 0)
    if not per_page or not pages:
        value = 0.0
    else:
        densities = sorted(per_page.values())
        median = densities[len(densities) // 2]
        mean = sum(densities) / pages
        value = min(1.0, mean / max(1, median))
    passed, marginal = _ge(value, th.extraction_sufficiency_min, th.edge_band_epsilon)
    return IndicatorResult(
        "extraction_sufficiency", 7, "抽取充分性", value, th.extraction_sufficiency_min,
        passed, marginal, {"pages": pages},
    )


def qa_pair_completeness(ir: IRDocument, th: QcThresholds) -> IndicatorResult:
    """P-QA 专属:完整问答对数 ÷ 检测到的「问」标记数(边界识别失败 = 漏对,计入此指标)。"""
    scan = detect_qa_pairs(ir)
    markers = scan.question_markers
    value = len(scan.pairs) / markers if markers else 0.0
    passed, marginal = _ge(value, th.qa_pair_completeness_min, th.edge_band_epsilon)
    return IndicatorResult(
        "qa_pair_completeness", 8, "问答对完整率", value, th.qa_pair_completeness_min,
        passed, marginal, {"pairs": len(scan.pairs), "question_markers": markers},
    )


ALL_INDICATORS = [
    clause_coverage,
    clause_continuity,
    hierarchy_legality,
    page_anchor_complete,
    table_consistency,
    text_quality,
    extraction_sufficiency,
]

# profile → 该 corpus_type 应跑的指标集。
# P-INT/P-EXT(制度):条款树全七项。
# P-QA/P-CASE(短、结构天然不均的非制度内容):跳过条款树四项(1/2/3/5),**也跳过抽取充分性(7)**——
# 指标7 量的是"页间密度均匀度"(均值/中位每页字数),假定制度满版页;问答/处罚决定书正文页满、
# 落款/尾页稀疏会被误判,故不适用。P-QA 跑 qa_pair_completeness + 锚点(4)/文本质量(6);
# P-CASE 只跑锚点(4)/文本质量(6),其质量闸是 §9 字段完整率(从 cases 表算,批次度量,非 s2 拦截)。
_CLAUSE_INDICATORS = ALL_INDICATORS
_QA_INDICATORS = [
    qa_pair_completeness,
    page_anchor_complete,
    text_quality,
]
_CASE_INDICATORS = [
    page_anchor_complete,
    text_quality,
]
_PROFILE_INDICATORS = {"P-QA": _QA_INDICATORS, "P-CASE": _CASE_INDICATORS}


def indicators_for(corpus_type: str) -> list:
    """按 corpus_type 选指标集;未登记的(P-INT/P-EXT/未知/空)走条款树全七项。"""
    return _PROFILE_INDICATORS.get(corpus_type, _CLAUSE_INDICATORS)
