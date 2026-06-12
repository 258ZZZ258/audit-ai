import pytest

from pipeline.chunking.clause_tree import (
    NodeType,
    build_tree,
    classify_heading,
    find_internal_refs,
    iter_articles,
)
from pipeline.ir import Block, BlockType


def blk(i: int, text: str) -> Block:
    return Block(index=i, type=BlockType.PARAGRAPH, text=text)


@pytest.mark.parametrize(
    "text,ntype,number",
    [
        ("第一章 总则", NodeType.CHAPTER, "1"),
        ("第二节 信息披露", NodeType.SECTION, "2"),
        ("第二十一条 信息披露义务人应当……", NodeType.ARTICLE, "21"),
        ("第二十一条之一 新增情形……", NodeType.ARTICLE, "21-1"),
        ("第二款 前款所称……", NodeType.CLAUSE, "2"),
        ("（三）其他情形", NodeType.ITEM, "3"),
        ("三、其他情形", NodeType.ITEM, "3"),
        ("①第一种", NodeType.SUBITEM, "1"),
        ("第 一 条 内容", NodeType.ARTICLE, "1"),  # 逐字加空格
    ],
)
def test_classify_heading(text, ntype, number):
    h = classify_heading(text)
    assert h is not None
    assert h.type is ntype
    assert h.number == number


def test_classify_heading_non_heading():
    assert classify_heading("本条所称信息披露义务人，是指……") is None
    assert classify_heading("   ") is None


def test_build_tree_nesting_and_path_norm():
    blocks = [
        blk(0, "第一章 总则"),
        blk(1, "第一条 本办法依据……"),
        blk(2, "第二章 信息披露"),
        blk(3, "第一节 一般规定"),
        blk(4, "第十条 信息披露义务人应当……"),
        blk(5, "前款所称披露，是指……"),  # 第十条 的正文
        blk(6, "第十条之一 新增披露情形……"),
    ]
    root = build_tree(blocks)
    arts = iter_articles(root)
    assert [a.number for a in arts] == ["1", "10", "10-1"]

    a1, a10, a10_1 = arts
    assert a1.clause_path_norm() == "1/1"  # 第一章 / 第一条(无节)
    assert a10.clause_path_norm() == "2/1/10"  # 第二章 / 第一节 / 第十条
    assert a10_1.clause_path_norm() == "2/1/10-1"
    assert a10.clause_path() == "第二章 > 第一节 > 第十条"
    # 第十条 覆盖 heading(4)+正文(5);之一(6)是兄弟条,不计入
    assert a10.collect_block_indices() == [4, 5]


def test_virtual_root_for_chapterless_notice():
    blocks = [
        blk(0, "关于规范费用报销的通知"),  # 无章前言 → 挂虚拟根
        blk(1, "第一条 为规范费用报销……"),
        blk(2, "第二条 报销审批权限如下……"),
    ]
    root = build_tree(blocks)
    assert root.type is NodeType.ROOT
    assert 0 in root.body_block_indices
    arts = iter_articles(root)
    assert [a.number for a in arts] == ["1", "2"]
    # 无章 → path_norm 仅条号
    assert arts[0].clause_path_norm() == "1"
    assert arts[0].parent is root


def test_find_internal_refs():
    text = "依照第二十一条之一和第三章的规定，参见第五条第二款。"
    refs = find_internal_refs(text)
    got = [(r.level, r.number) for r in refs]
    assert got == [("条", "21-1"), ("章", "3"), ("条", "5"), ("款", "2")]
