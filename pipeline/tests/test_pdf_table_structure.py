import io

import pytest

from common.ir import BlockType
from pipeline.parsing.light_parser import LightParser


def pdf_bytes():
    canvas = pytest.importorskip("reportlab.pdfgen.canvas")
    stream = io.BytesIO()
    pdf = canvas.Canvas(stream, pagesize=(400, 500))
    pdf.drawString(30, 460, "Before the table")
    # Closed cells; first column spans both data rows geometrically.
    for x in (30, 130, 350):
        pdf.line(x, 260, x, 410)
    for y in (410, 360, 260):
        pdf.line(30, y, 350, y)
    pdf.line(130, 310, 350, 310)
    pdf.drawString(40, 390, "Department")
    pdf.drawString(140, 390, "Measures")
    pdf.drawString(40, 335, "Alpha")
    pdf.drawString(140, 340, "First distinct issue")
    pdf.drawString(140, 325, "still pending")
    pdf.drawString(140, 290, "Second distinct issue")
    pdf.drawString(140, 275, "completed")
    pdf.drawString(30, 220, "After the table")
    pdf.showPage()
    pdf.drawString(30, 450, "Plain page without a table")
    pdf.save()
    return stream.getvalue()


def test_ruled_pdf_preserves_rows_spans_and_surrounding_text_once():
    result = LightParser().parse(pdf_bytes(), "pdf", scanned_char_per_page_max=1)
    assert result.ok
    table_blocks = [b for b in result.blocks if b.type == BlockType.TABLE]
    assert len(table_blocks) == 1
    table = table_blocks[0].table
    assert table.n_rows == 3 and table.n_cols == 2
    assert table.header_rows == 0  # Unknown first row must not silently disappear.
    assert any(c.text == "Alpha" and c.rowspan == 2 for c in table.cells)
    rows = table.expanded_rows()
    assert rows[1][0] == rows[2][0] == "Alpha"
    assert "pending" in rows[1][1] and "completed" not in rows[1][1]
    assert "completed" in rows[2][1] and "pending" not in rows[2][1]
    paragraphs = "\n".join(b.text for b in result.blocks if b.type != BlockType.TABLE)
    assert "distinct issue" not in paragraphs
    assert paragraphs.count("Before the table") == 1
    assert paragraphs.count("After the table") == 1
    assert "Plain page without a table" in paragraphs
    assert [b.index for b in result.blocks] == list(range(len(result.blocks)))
    assert table_blocks[0].page == 1
    assert result.blocks[-1].page == 2
