"""Phase 1:profile 路由分流(s3 按 corpus_type 选切块策略)。纯单测,无栈。"""

from __future__ import annotations

from common.ir import Block, BlockType, IRDocument
from pipeline.chunking.profile_router import build_specs
from pipeline.config import ChunkConfig

_CFG = ChunkConfig(target_token_min=300, target_token_max=600, parent_block_token_max=2000)


def _clause_doc() -> IRDocument:
    return IRDocument(
        doc_version_id="DVROUTE",
        source_format="docx",
        page_count=1,
        blocks=[
            Block(index=0, type=BlockType.HEADING, text="第一章 总则", page=1),
            Block(index=1, type=BlockType.PARAGRAPH, text="第一条 本办法用于路由测试。", page=1),
        ],
    )


def test_clause_profiles_use_clause_tree() -> None:
    # P-INT / P-EXT / 未知 / 空 都走条款树(历史行为不变)
    for ct in ("P-INT", "P-EXT", "UNKNOWN", ""):
        specs = build_specs(_clause_doc(), ct, _CFG)
        assert any(s.clause_path_norm for s in specs), f"{ct} 应产出条款块"
        assert all(s.chunk_type in ("clause", "table") for s in specs)


def _qa_doc() -> IRDocument:
    return IRDocument(
        doc_version_id="DVROUTEQA",
        source_format="docx",
        page_count=1,
        blocks=[
            Block(index=0, type=BlockType.PARAGRAPH, text="问:路由测试问句?", page=1),
            Block(index=1, type=BlockType.PARAGRAPH, text="答:路由测试答句。", page=1),
        ],
    )


def test_qa_dispatches_to_qa_builder() -> None:
    # Phase 2 已实现:P-QA 分流到问答切分,产出 chunk_type="qa"
    specs = build_specs(_qa_doc(), "P-QA", _CFG)
    assert specs and all(s.chunk_type == "qa" for s in specs)
    assert specs[0].clause_path_norm == "qa/1"


def _case_doc() -> IRDocument:
    return IRDocument(
        doc_version_id="DVROUTECASE",
        source_format="docx",
        page_count=1,
        title="某某行政处罚决定书",
        blocks=[
            Block(index=0, type=BlockType.PARAGRAPH, text="当事人:某某公司。", page=1),
            Block(index=1, type=BlockType.PARAGRAPH, text="经查,该公司存在违规行为。", page=1),
        ],
    )


def test_case_dispatches_to_case_builder() -> None:
    # Phase 3 已实现:P-CASE 分流到案例切分,产出 case_section + case_summary
    specs = build_specs(_case_doc(), "P-CASE", _CFG)
    types = {s.chunk_type for s in specs}
    assert types == {"case_section", "case_summary"}
    assert specs[0].clause_path_norm == "case/1"
