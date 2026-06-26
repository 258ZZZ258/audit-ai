"""T0.2:Table.to_markdown / expanded_rows —— 合并单元格按 rowspan/colspan 展开补值。"""

from common.ir import Table, TableCell


def test_expanded_rows_fills_colspan():
    # 一行:A 跨两列 + B → [[A, A, B]]
    t = Table(
        n_rows=1,
        n_cols=3,
        cells=[
            TableCell(text="A", row=0, col=0, colspan=2),
            TableCell(text="B", row=0, col=2),
        ],
        header_rows=1,
    )
    assert t.expanded_rows() == [["A", "A", "B"]]


def test_expanded_rows_fills_rowspan():
    t = Table(
        n_rows=2,
        n_cols=2,
        cells=[
            TableCell(text="H", row=0, col=0, rowspan=2),
            TableCell(text="x", row=0, col=1),
            TableCell(text="y", row=1, col=1),
        ],
        header_rows=1,
    )
    assert t.expanded_rows() == [["H", "x"], ["H", "y"]]


def test_to_markdown_has_header_separator():
    t = Table(
        n_rows=2,
        n_cols=2,
        cells=[
            TableCell(text="费用项目", row=0, col=0),
            TableCell(text="标准", row=0, col=1),
            TableCell(text="差旅", row=1, col=0),
            TableCell(text="500", row=1, col=1),
        ],
        header_rows=1,
    )
    lines = t.to_markdown().splitlines()
    assert lines[0] == "| 费用项目 | 标准 |"
    assert lines[1] == "| --- | --- |"
    assert lines[2] == "| 差旅 | 500 |"
