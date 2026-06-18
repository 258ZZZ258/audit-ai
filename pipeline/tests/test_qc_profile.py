"""Phase 2:profile-aware QC 纯单测(无栈)。

P-QA 跑 qa_pair_completeness + 指标 4/6/7;
跳过条款树四项 clause_coverage(1)/clause_continuity(2)/hierarchy_legality(3)/table_consistency(5)。
"""

from __future__ import annotations

from common.ir import Block, BlockType, IRDocument
from pipeline.config import load_config
from pipeline.qc.gate import evaluate
from pipeline.qc.indicators import indicators_for

_CLAUSE_INDEXES = {1, 2, 3, 5}  # 条款树四项,P-QA 不跑


def _doc(lines, dvid="DVQAQC", page_count=1) -> IRDocument:
    blocks = [
        Block(index=i, type=BlockType.PARAGRAPH, text=t, page=p) for i, (t, p) in enumerate(lines)
    ]
    return IRDocument(
        doc_version_id=dvid, source_format="docx", page_count=page_count, blocks=blocks
    )


def _complete_qa():
    return [
        ("问:内控制度多久更新一次?", 1),
        ("答:原则上每年评估一次,重大变化随时修订。", 1),
        ("问:谁负责审批内控制度?", 1),
        ("答:由内控管理委员会审批。", 1),
    ]


def _unmatched_qa():
    return [
        ("问:有答的问题?", 1),
        ("答:这是答案。", 1),
        ("问:没有答的问题?", 1),  # 缺答 → 完整率 1/2
    ]


def test_pqa_selects_three_indicators_no_extraction_sufficiency() -> None:
    inds = {fn.__name__ for fn in indicators_for("P-QA")}
    # 指标7 抽取充分性(页密度均匀度)对短/不均的问答件误伤,已移除
    assert inds == {"qa_pair_completeness", "page_anchor_complete", "text_quality"}
    assert "extraction_sufficiency" not in inds


def test_pqa_complete_doc_passes_with_full_completeness() -> None:
    r = evaluate(_doc(_complete_qa()), load_config().qc, "P-QA")
    ind = next(i for i in r.indicators if i.key == "qa_pair_completeness")
    assert ind.value == 1.0 and ind.passed
    assert not r.failed
    # 不跑条款树四项
    assert _CLAUSE_INDEXES.isdisjoint({i.index for i in r.indicators})


def test_pqa_unmatched_question_lowers_completeness_and_fails() -> None:
    r = evaluate(_doc(_unmatched_qa()), load_config().qc, "P-QA")
    ind = next(i for i in r.indicators if i.key == "qa_pair_completeness")
    assert ind.value < 1.0  # 0.5 < 0.95 阈值
    assert not ind.passed and r.failed
    assert ind.evidence["question_markers"] == 2 and ind.evidence["pairs"] == 1


def test_pqa_does_not_run_clause_tree_indicators() -> None:
    # P-QA 文档无条款 → 若误跑条款树指标会 failed;profile 选择把它们排除掉,故不应失败
    r = evaluate(_doc(_complete_qa()), load_config().qc, "P-QA")
    keys = {i.key for i in r.indicators}
    assert "clause_coverage" not in keys
    assert "clause_continuity" not in keys
    assert "hierarchy_legality" not in keys
    assert "table_consistency" not in keys


def test_clause_profile_still_runs_seven_indicators() -> None:
    # P-INT/未知 行为不变:仍全七项
    r = evaluate(_doc(_complete_qa()), load_config().qc, "P-INT")
    assert {i.index for i in r.indicators} == {1, 2, 3, 4, 5, 6, 7}
    assert "qa_pair_completeness" not in {i.key for i in r.indicators}


def _case_doc():
    return [
        ("当事人:某某证券有限公司,住所地北京市。", 1),
        ("经查,该公司存在违规行为。", 1),
        ("现决定:对当事人处以罚款50万元。", 1),
    ]


def test_pcase_selects_two_indicators_no_extraction_sufficiency() -> None:
    inds = {fn.__name__ for fn in indicators_for("P-CASE")}
    # 指标7 对短决定书(落款页稀疏)误伤,已移除;案例质量闸是 §9 字段完整率
    assert inds == {"page_anchor_complete", "text_quality"}
    assert "extraction_sufficiency" not in inds


def test_pcase_skips_clause_tree_and_qa_indicators() -> None:
    r = evaluate(_doc(_case_doc()), load_config().qc, "P-CASE")
    keys = {i.key for i in r.indicators}
    # 跳过条款树四项(1/2/3/5)+ 问答指标
    assert _CLAUSE_INDEXES.isdisjoint({i.index for i in r.indicators})
    assert "qa_pair_completeness" not in keys
    # 只跑锚点(4)/文本质量(6);抽取充分性(7)对短决定书误伤已移除
    assert {i.index for i in r.indicators} == {4, 6}
