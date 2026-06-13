"""light 解析器:python-docx(docx 抽结构)+ pdfplumber(pdf 文本层)→ IR。

- docx:按文档序抽段落与表格;``page`` 置 None(待 B4 文本对齐从渲染件回填)。
- pdf:pdfplumber 逐页抽文本,``page`` 原生给出;字符密度 < 阈值 → 判扫描件(E202-DEMO 隔离)。
- 其它格式 → E101-DEMO(白名单外;通常 s0 已先拦)。
"""

from __future__ import annotations

import io

import pdfplumber
from docx import Document as DocxDoc
from docx.oxml.ns import qn
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph

from pipeline.chunking.normalize import strip_ws
from pipeline.ir import Block, BlockType, Table, TableCell
from pipeline.parsing.adapter import ParserAdapter, ParseResult
from pipeline.states import ErrorCode


def _iter_block_items(doc):
    """按文档顺序产出 Paragraph 与 Table(python-docx 的两者分列,需遍历 body)。"""
    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, doc)
        elif child.tag == qn("w:tbl"):
            yield DocxTable(child, doc)


def _build_table(t: DocxTable) -> Table:
    n_rows, n_cols = len(t.rows), len(t.columns)
    cells = []
    for r in range(n_rows):
        for c in range(n_cols):
            try:
                txt = t.cell(r, c).text
            except IndexError:
                txt = ""
            cells.append(TableCell(text=txt, row=r, col=c))
    return Table(n_rows=n_rows, n_cols=n_cols, cells=cells, header_rows=1)


def _docx_blocks(data: bytes) -> tuple[list[Block], str | None]:
    doc = DocxDoc(io.BytesIO(data))
    blocks: list[Block] = []
    title: str | None = None
    idx = 0
    for item in _iter_block_items(doc):
        if isinstance(item, Paragraph):
            if not item.text.strip():
                continue
            style = item.style.name if item.style else None
            is_heading = (style or "").startswith("Heading")
            btype = BlockType.HEADING if is_heading else BlockType.PARAGRAPH
            blocks.append(Block(index=idx, type=btype, text=item.text, style=style))
            if title is None:
                title = item.text.strip()
            idx += 1
        else:
            blocks.append(Block(index=idx, type=BlockType.TABLE, table=_build_table(item)))
            idx += 1
    return blocks, title


def _pdf_result(data: bytes, scanned_max: int) -> ParseResult:
    blocks: list[Block] = []
    total_chars = 0
    idx = 0
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        npages = len(pdf.pages)
        for pno, page in enumerate(pdf.pages, start=1):
            txt = page.extract_text() or ""
            total_chars += len(strip_ws(txt))
            for line in txt.split("\n"):
                if line.strip():
                    blocks.append(Block(index=idx, type=BlockType.PARAGRAPH, text=line, page=pno))
                    idx += 1
    density = total_chars / max(1, npages)
    if density < scanned_max:
        return ParseResult(
            error_code=ErrorCode.SCANNED_OCR_DISABLED.value,
            reason=f"字符密度 {density:.0f} < {scanned_max}/页,疑似扫描件,OCR 未启用",
        )
    return ParseResult(blocks=blocks, page_count=npages, title=blocks[0].text if blocks else None)


class LightParser(ParserAdapter):
    def parse(
        self, data: bytes, source_format: str, *, scanned_char_per_page_max: int
    ) -> ParseResult:
        if source_format == "docx":
            blocks, title = _docx_blocks(data)
            return ParseResult(blocks=blocks, page_count=None, title=title)
        if source_format == "pdf":
            return _pdf_result(data, scanned_char_per_page_max)
        return ParseResult(
            error_code=ErrorCode.FORMAT_NOT_WHITELISTED.value,
            reason=f"light 解析器不支持格式: {source_format}",
        )
