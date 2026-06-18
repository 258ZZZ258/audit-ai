"""Phase 2:P-QA 问答切分纯单测(无栈)。一问一答 = 1 chunk;确定性 chunk_id。"""

from __future__ import annotations

from common.ir import Block, BlockType, IRDocument
from pipeline.chunking.qa_chunker import build_qa_specs, detect_qa_pairs
from pipeline.config import ChunkConfig

_CFG = ChunkConfig(target_token_min=300, target_token_max=600, parent_block_token_max=2000)


def _doc(lines, dvid="DVQA") -> IRDocument:
    blocks = [
        Block(index=i, type=BlockType.PARAGRAPH, text=t, page=p) for i, (t, p) in enumerate(lines)
    ]
    return IRDocument(doc_version_id=dvid, source_format="docx", page_count=1, blocks=blocks)


def _explicit_doc() -> IRDocument:
    # 显式「问:/答:」三问答对
    return _doc(
        [
            ("问:内控制度多久更新一次?", 1),
            ("答:原则上每年评估一次,重大变化随时修订。", 1),
            ("问:谁负责审批内控制度?", 2),
            ("答:由内控管理委员会审批。", 2),
            ("问:制度发布后如何宣贯?", 2),
            ("答:通过培训与内网公告宣贯。", 3),
        ]
    )


def _numbered_doc() -> IRDocument:
    # 编号问答体:1、问句 / 答:答句
    return _doc(
        [
            ("1、什么是关联交易?", 1),
            ("答:指公司与关联方之间的交易。", 1),
            ("2．关联交易需要披露吗?", 2),
            ("答:达到标准的须按规定披露。", 2),
        ]
    )


def test_explicit_pairs_one_chunk_each() -> None:
    specs = build_qa_specs(_explicit_doc(), _CFG)
    assert len(specs) == 3
    assert all(s.chunk_type == "qa" for s in specs)
    assert all(not s.is_parent and not s.is_table for s in specs)
    assert all(s.parent_chunk_id is None and s.internal_refs is None for s in specs)
    assert all(s.embed_status == "pending" and s.seq == 0 for s in specs)
    assert [s.clause_path_norm for s in specs] == ["qa/1", "qa/2", "qa/3"]
    assert [s.clause_path for s in specs] == ["问答/1", "问答/2", "问答/3"]


def test_breadcrumb_is_question_and_text_has_both() -> None:
    specs = build_qa_specs(_explicit_doc(), _CFG)
    first = specs[0]
    assert first.breadcrumb == "内控制度多久更新一次?"  # 问句加权进面包屑
    assert first.text.startswith("内控制度多久更新一次?")  # 面包屑前缀
    assert "问:内控制度多久更新一次?" in first.text
    assert "答:原则上每年评估一次" in first.text  # 正文含问与答


def test_deterministic_chunk_id() -> None:
    a = build_qa_specs(_explicit_doc(), _CFG)
    b = build_qa_specs(_explicit_doc(), _CFG)  # 同输入两次
    assert [s.chunk_id for s in a] == [s.chunk_id for s in b]
    assert len({s.chunk_id for s in a}) == len(a)  # 各对 id 互异


def test_numbered_qa_form() -> None:
    specs = build_qa_specs(_numbered_doc(), _CFG)
    assert len(specs) == 2
    assert specs[0].breadcrumb == "什么是关联交易?"  # 编号前缀被剥离
    assert "答:指公司与关联方之间的交易。" in specs[0].text
    assert specs[1].breadcrumb == "关联交易需要披露吗?"  # 全角点「．」编号


def test_multiblock_answer_spans_until_next_question() -> None:
    doc = _doc(
        [
            ("问:报销流程是什么?", 1),
            ("答:第一步提交单据;", 1),
            ("第二步部门审批;", 1),  # 答句续行(无标记,归入上一答)
            ("第三步财务复核。", 2),
            ("问:报销时限多久?", 2),
            ("答:三个工作日内。", 2),
        ]
    )
    specs = build_qa_specs(doc, _CFG)
    assert len(specs) == 2
    assert "第二步部门审批" in specs[0].text and "第三步财务复核" in specs[0].text
    assert specs[0].page_start == 1 and specs[0].page_end == 2  # 跨页问答对页跨度


def test_question_without_answer_not_emitted() -> None:
    doc = _doc(
        [
            ("问:有答的问题?", 1),
            ("答:这是答案。", 1),
            ("问:没有答的问题?", 2),  # 缺「答:」→ 不成对
        ]
    )
    specs = build_qa_specs(doc, _CFG)
    assert len(specs) == 1
    assert specs[0].breadcrumb == "有答的问题?"
    # 但「问」标记仍被检测到(质检分母用)
    scan = detect_qa_pairs(doc)
    assert scan.question_markers == 2 and len(scan.pairs) == 1


def test_no_qa_boundary_returns_empty() -> None:
    doc = _doc([("这是一段普通正文,既无问也无答。", 1), ("另一段普通正文。", 1)])
    assert build_qa_specs(doc, _CFG) == []
