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
        ("第21bis条 西文插入条", NodeType.ARTICLE, "21-1"),
        ("第21ter条 第二个插入", NodeType.ARTICLE, "21-2"),
        ("第21.1b条 小数式插入条", NodeType.ARTICLE, "21-1"),
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
    # 「第三方协议条款」不是条标题(号非「条」前合法数字),不应误判
    assert classify_heading("第三方协议条款应当明确双方权利义务") is None


def test_cross_law_reference_not_treated_as_article():
    # 跨法引用列举(第X条 紧跟、,;)→ 非条标题(发现2 修复:块以「…第一百九十六条、依照《证券法》…」起)
    assert classify_heading("第一百九十六条、依照《证券法》第一百九十七条进行行政处罚，") is None
    assert classify_heading("第二百一十三条，第二百一十四条规定的情形") is None
    # 真条标题(条后跟正文字)与号单独成行(条后到行尾)仍正常识别
    h = classify_heading("第四十七条 本办法自发布之日起施行")
    assert h is not None and h.type is NodeType.ARTICLE and h.number == "47"
    h2 = classify_heading("第四十七条")
    assert h2 is not None and h2.type is NodeType.ARTICLE and h2.number == "47"


# ── 小数编号(交易所规则体例:2.17 / 3.1.2),做全小数规则 ─────────────────────
@pytest.mark.parametrize(
    "text, number",
    [
        ("2.17 上市公司拟披露的信息存在不确定性", "2.17"),  # 章.条
        ("3.1.2 董事、监事和高级管理人员应当", "3.1.2"),  # 章.节.条
        ("10.2.5 上市公司与关联人发生的交易", "10.2.5"),
    ],
)
def test_decimal_article_recognized(text, number):
    h = classify_heading(text)
    assert h is not None and h.type is NodeType.ARTICLE and h.number == number  # 全小数保留


def test_decimal_false_positives_not_matched():
    # 号后无空白的正文小数不误判为条:百分比 / 金额单位
    assert classify_heading("2.17%以上的表决权") is None
    assert classify_heading("1.5亿元的注册资本") is None
    # 「N.M.K 条…」是「第N.M.K条」引用碎片(第+前段在上一块),非真条
    assert classify_heading("10.1.3 条或者第 10.1.5 条规定的情形之一；") is None
    assert classify_heading("14.1.1 条第（六）项规定的标准") is None


def test_classify_heading_is_context_free():
    # classify_heading 现为纯单行分类:目录判定上移到 build_tree 区域预扫,
    # 故「第一章 总则」(无页码/点引导)仍正常识别为章。
    h = classify_heading("第一章 总则")
    assert h is not None and h.type is NodeType.CHAPTER


def _chapters(root):
    return [c.raw_label for c in root.children if c.type is NodeType.CHAPTER]


def test_toc_stripped_by_dotted_leader():
    # 信号①点引导符(≥4 连续点/省略号)→ 单行即判目录(正文绝不出现),长度不限
    blocks = [
        blk(0, "第一章 总则 " + "." * 40 + " 5"),
        blk(1, "第二节 董事会秘书 …………………………… 12"),
        blk(2, "第一章 总则"),
        blk(3, "第一条 正文内容"),
    ]
    root = build_tree(blocks)
    assert _chapters(root) == ["第一章"]  # 目录的「第一章」不重复成节点
    assert root.body_block_indices == [0, 1]  # scheme A:目录行留作根 body


def test_toc_stripped_by_explicit_anchor_even_when_short():
    # 信号②显式「目录」锚 → 其后紧邻候选行阈值降为 1(覆盖只有一两项、无点引导的短目录)
    blocks = [
        blk(0, "目 录"),
        blk(1, "第一章 总则 1"),
        blk(2, "第二章 附则 3"),
        blk(3, "第一章 总则"),
        blk(4, "第一条 正文内容"),
        blk(5, "第二章 附则"),
        blk(6, "第二条 正文内容"),
    ]
    root = build_tree(blocks)
    assert _chapters(root) == ["第一章", "第二章"]
    assert root.body_block_indices == [0, 1, 2]  # 锚 + 两条目录项


def test_toc_stripped_by_trailing_page_run_covers_decimal_and_article():
    # 信号③无锚无点引导:连续 ≥3 行「文本+末尾页码」成簇 → 目录。统一覆盖 章/条/小数体例
    # 目录项(旧版逐行正则只认 章/节,会漏后两者——尤其小数项会被误当真 ARTICLE)。
    blocks = [
        blk(0, "第一章 总则 1"),
        blk(1, "第一条 定义 2"),
        blk(2, "2.17 交易行为规范 15"),
        blk(3, "第一章 总则"),
        blk(4, "第一条 正文内容"),
    ]
    root = build_tree(blocks)
    assert _chapters(root) == ["第一章"]
    assert root.body_block_indices == [0, 1, 2]
    assert "2.17" not in [a.raw_label for a in iter_articles(root)]


def test_isolated_heading_ending_in_number_not_stripped():
    # 反向误伤防护:孤立一行真标题恰以数字结尾(run=1、无锚无点引导)→ 不剥
    blocks = [
        blk(0, "第一条 正文一"),
        blk(1, "第二条 二〇二四年度计划 2024"),
        blk(2, "第三条 正文三"),
    ]
    root = build_tree(blocks)
    assert [a.raw_label for a in iter_articles(root)] == ["第一条", "第二条", "第三条"]


def test_decimal_cross_section_ordering_no_false_violation():
    # 全小数元组排序:跨节(10.1.x → 10.2.x)即便节点未识别为父级,也不被层级合法性误判
    from pipeline.qc.indicators import _key

    assert _key("10.2.1") > _key("10.1.3")  # (10,2,1) > (10,1,3)
    assert _key("3.1.2") > _key("3.1.1")
    assert _key("4-1") > _key("4")  # 插入条仍 (4,1) > (4,)
    assert not (_key("3") > _key("5"))  # 逆序仍被判(3,)<=(5,)


def test_build_tree_and_refs_handle_bis():
    blocks = [
        blk(0, "第二十一条 一般情形……"),
        blk(1, "第21bis条 新增的西文插入条规定如下。"),
        blk(2, "前述适用第21bis条与第二十一条之一的规定。"),  # 正文引用
    ]
    root = build_tree(blocks)
    assert [a.number for a in iter_articles(root)] == ["21", "21-1"]  # bis 进树
    refs = [(r.level, r.number) for r in find_internal_refs(blocks[2].text)]
    assert ("条", "21-1") in refs


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
