from common.ir import Block, BlockType, Table, TableCell
from pipeline.parsing.page_align import align_blocks, align_pages


def test_monotonic_exact_per_page():
    pages = ["第一条 总则。", "第二条 适用范围。", "第三条 附则。"]
    blocks = ["第一条 总则。", "第二条 适用范围。", "第三条 附则。"]
    spans = align_pages(blocks, pages, fuzzy_threshold=90)
    assert spans == [(1, 1), (2, 2), (3, 3)]


def test_cross_page_span():
    # 渲染件把一句话拆到两页;去空白拼接后 block 是连续子串
    pages = ["第三条 当事人应", "当遵守规定。"]
    blocks = ["第三条 当事人应当遵守规定。"]
    spans = align_pages(blocks, pages, fuzzy_threshold=90)
    assert spans == [(1, 2)]  # 跨页 page_start=1 page_end=2


def test_duplicate_text_disambiguated_by_monotonicity():
    pages = ["第一条 总则。第八条 删除。", "第二条 其他。", "第八条 删除。"]
    blocks = ["第一条 总则。", "第八条 删除。", "第二条 其他。", "第八条 删除。"]
    spans = align_pages(blocks, pages, fuzzy_threshold=90)
    # 两个相同的"第八条 删除。"分别落到 page1 与 page3(单调消歧)
    assert spans == [(1, 1), (1, 1), (2, 2), (3, 3)]


def test_symmetric_normalization_handles_spacing_and_fullwidth():
    pages = ["第 一 条　内容。"]  # 逐字加空格 + 全角空格
    blocks = ["第一条 内容。"]
    spans = align_pages(blocks, pages, fuzzy_threshold=90)
    assert spans == [(1, 1)]


def test_fuzzy_fallback_when_exact_misses():
    pages = ["甲方乙方丙方戊方签订协议。"]
    blocks = ["甲方乙方丙方丁方签订协议。"]  # 戊→丁 一字之差,精确未中
    exact = align_pages(blocks, pages, fuzzy_threshold=200)  # 阈值过高 → 不兜底
    assert exact == [(None, None)]
    fuzzy = align_pages(blocks, pages, fuzzy_threshold=70)  # 放宽 → 兜底命中 page1
    assert fuzzy == [(1, 1)]


def test_miss_yields_none():
    pages = ["第一条 总则。"]
    blocks = ["完全不相关的另一段文字内容。"]
    spans = align_pages(blocks, pages, fuzzy_threshold=90)
    assert spans == [(None, None)]


def test_align_blocks_sets_page_and_skips_empty():
    table = Table(n_rows=1, n_cols=1, cells=[TableCell(text="x", row=0, col=0)])
    blocks = [
        Block(index=0, type=BlockType.PARAGRAPH, text="第一条 总则。"),
        Block(index=1, type=BlockType.PARAGRAPH, text="第二条 跨页内容继续"),
        Block(index=2, type=BlockType.TABLE, page=5, table=table),  # 空文本表格块
    ]
    pages = ["第一条 总则。第二条 跨页", "内容继续"]
    out = align_blocks(blocks, pages, fuzzy_threshold=90)
    assert out[0].page == 1 and out[0].page_end is None  # 同页 → page_end None
    assert out[1].page == 1 and out[1].page_end == 2  # 跨页 → page_end=2
    assert out[2].page == 5  # 空文本表格块跳过,解析器给的页保持
