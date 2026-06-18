"""Phase 3:P-CASE 案例切分纯单测(无栈)。要素分段 + 全文摘要块;确定性 chunk_id。"""

from __future__ import annotations

from common.ir import Block, BlockType, IRDocument
from pipeline.chunking.case_chunker import build_case_specs
from pipeline.config import ChunkConfig

_CFG = ChunkConfig(target_token_min=300, target_token_max=600, parent_block_token_max=2000)


def _doc(lines, dvid="DVCASE", title="某某行政处罚决定书") -> IRDocument:
    blocks = [
        Block(index=i, type=BlockType.PARAGRAPH, text=t, page=p) for i, (t, p) in enumerate(lines)
    ]
    return IRDocument(
        doc_version_id=dvid, source_format="docx", page_count=1, title=title, blocks=blocks
    )


def _four_element_doc() -> IRDocument:
    return _doc(
        [
            ("当事人:某某证券有限公司,住所地北京市。", 1),
            ("经查,该公司存在以下违规行为:未按规定披露信息。", 1),
            ("依据《证券法》第一百九十七条的规定,", 2),
            ("现决定:对当事人处以罚款50万元。", 2),
        ]
    )


def test_four_element_doc_yields_sections_and_one_summary() -> None:
    specs = build_case_specs(_four_element_doc(), _CFG)
    types = [s.chunk_type for s in specs]
    assert types.count("case_summary") == 1
    sections = [s for s in specs if s.chunk_type == "case_section"]
    assert len(sections) == 4  # 当事人 / 违规事实 / 处罚依据 / 处罚决定
    # 全局 1-based 序:case/1..case/5(含摘要块)
    assert [s.clause_path_norm for s in specs] == ["case/1", "case/2", "case/3", "case/4", "case/5"]
    assert all(s.seq == 0 for s in specs)
    assert all(not s.is_parent and not s.is_table for s in specs)
    assert all(s.parent_chunk_id is None and s.internal_refs is None for s in specs)
    assert all(s.embed_status == "pending" for s in specs)


def test_breadcrumb_has_section_name_and_title() -> None:
    specs = build_case_specs(_four_element_doc(), _CFG)
    first = specs[0]
    assert first.breadcrumb == "《某某行政处罚决定书》 > 当事人"
    assert first.text.startswith("《某某行政处罚决定书》 > 当事人")
    assert "某某证券有限公司" in first.text  # 面包屑后接正文
    assert first.clause_path == "案例/当事人"
    # 各段名都进了对应面包屑
    names = {s.breadcrumb.split(" > ")[1] for s in specs if s.chunk_type == "case_section"}
    assert names == {"当事人", "违规事实", "处罚依据", "处罚决定"}


def test_summary_block_is_rule_based_and_truncated() -> None:
    specs = build_case_specs(_four_element_doc(), _CFG)
    summary = next(s for s in specs if s.chunk_type == "case_summary")
    assert summary.breadcrumb == "《某某行政处罚决定书》 > 摘要"
    assert "某某行政处罚决定书" in summary.text  # 含标题
    assert "某某证券有限公司" in summary.text  # 含当事人
    # 正文(去面包屑)受 ~150 字截断
    body = summary.text.split("\n", 1)[1]
    assert len(body) <= 150


def test_deterministic_chunk_id() -> None:
    a = build_case_specs(_four_element_doc(), _CFG)
    b = build_case_specs(_four_element_doc(), _CFG)
    assert [s.chunk_id for s in a] == [s.chunk_id for s in b]
    assert len({s.chunk_id for s in a}) == len(a)  # 各块 id 互异


def test_page_span_from_section_blocks() -> None:
    specs = build_case_specs(_four_element_doc(), _CFG)
    dep = next(s for s in specs if s.breadcrumb.endswith("处罚依据"))
    assert dep.page_start == 2 and dep.page_end == 2


def test_no_section_marker_falls_back_to_single_section_plus_summary() -> None:
    doc = _doc([("一段没有任何要素段首标记的普通正文。", 1), ("另一段普通正文。", 1)])
    specs = build_case_specs(doc, _CFG)
    assert len(specs) == 2  # 兜底:1 个 case_section + 1 个 case_summary(决定书必可检索)
    sec = next(s for s in specs if s.chunk_type == "case_section")
    assert sec.clause_path_norm == "case/1"
    assert sec.breadcrumb.endswith("全文")
    assert any(s.chunk_type == "case_summary" for s in specs)


def test_non_empty_doc_never_returns_empty() -> None:
    doc = _doc([("仅一段无标记文本。", 1)])
    assert build_case_specs(doc, _CFG)  # 非空文档绝不返回 []
