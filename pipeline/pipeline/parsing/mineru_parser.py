"""MinerU pipeline 后端:扫描件/图片 OCR → IR blocks(§4.1)。

映射 MinerU ``middle.json`` → IR ``Block``(块级 ``ocr_conf=min(span scores)``)。
``MinerUParser``(T2)接 in-process ``do_parse``;``mineru`` import 延迟到 ``parse`` 内
(避免默认装载 + multiprocessing 在 import 期触发)。
"""

from __future__ import annotations

import glob
import json
import os
import tempfile
from html.parser import HTMLParser
from pathlib import Path

from common.ir import BBox, Block, BlockType, Table, TableCell
from pipeline.parsing.adapter import ParserAdapter, ParseResult
from pipeline.states import ErrorCode

# MinerU para_block.type → IR BlockType(table 单独处理;image/equation 等无文本 → 跳过)
_BTYPE = {
    "title": BlockType.HEADING,
    "text": BlockType.PARAGRAPH,
    "index": BlockType.PARAGRAPH,  # 目录块(多行)
    "list": BlockType.LIST_ITEM,
}


def _bbox(raw) -> BBox | None:
    if not raw or len(raw) != 4:
        return None
    x0, y0, x1, y1 = raw
    return BBox(x0=float(x0), y0=float(y0), x1=float(x1), y1=float(y1))


def _text_and_conf(block: dict) -> tuple[str, float | None]:
    """普通块:行内 span.content 拼接(line 间 \\n);``ocr_conf=min(span scores)``。"""
    lines_text: list[str] = []
    scores: list[float] = []
    for line in block.get("lines", []):
        parts = []
        for s in line.get("spans", []):
            if s.get("content"):
                parts.append(s["content"])
            if s.get("score") is not None:
                scores.append(s["score"])
        if parts:
            lines_text.append("".join(parts))
    return "\n".join(lines_text), (min(scores) if scores else None)


def _table_html(block: dict) -> str | None:
    """table 块:嵌套 ``blocks[].lines[].spans[]`` 里 type=table 的 ``html``(score 在块级,见下)。"""
    for inner in block.get("blocks", []):
        for line in inner.get("lines", []):
            for s in line.get("spans", []):
                if s.get("html"):
                    return s["html"]
    return None


class _TableHTMLParser(HTMLParser):
    """MinerU 表格 HTML(``<table><tr><td rowspan colspan>``)→ 行内单元格三元组。"""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[tuple[str, int, int]]] = []
        self._row: list | None = None
        self._span: tuple[int, int] | None = None
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._span = (int(a.get("rowspan", 1)), int(a.get("colspan", 1)))
            self._buf = []

    def handle_data(self, data):
        if self._span is not None:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._span is not None and self._row is not None:
            rs, cs = self._span
            self._row.append(("".join(self._buf).strip(), rs, cs))
            self._span = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None


def _html_to_table(html: str) -> Table:
    """HTML table → IR ``Table``(occupied 网格定位 row/col,保留 rowspan/colspan)。"""
    p = _TableHTMLParser()
    p.feed(html)
    cells: list[TableCell] = []
    occupied: set[tuple[int, int]] = set()
    for r, row in enumerate(p.rows):
        c = 0
        for text, rs, cs in row:
            while (r, c) in occupied:
                c += 1
            cells.append(TableCell(text=text, row=r, col=c, rowspan=rs, colspan=cs))
            for dr in range(rs):
                for dc in range(cs):
                    occupied.add((r + dr, c + dc))
            c += cs
    n_cols = max((cc.col + cc.colspan for cc in cells), default=0)
    return Table(n_rows=len(p.rows), n_cols=n_cols, cells=cells, header_rows=1)


def _mineru_to_blocks(middle: dict) -> list[Block]:
    """MinerU ``middle.json`` → IR ``Block`` 列表(discarded_blocks 页眉页脚不入;index 严格升序)。"""
    blocks: list[Block] = []
    idx = 0
    for page in middle.get("pdf_info", []):
        page_no = page.get("page_idx", 0) + 1
        for b in page.get("para_blocks", []):
            btype = b.get("type")
            bbox = _bbox(b.get("bbox"))
            if btype == "table":
                html = _table_html(b)
                if not html:
                    continue
                blocks.append(
                    Block(
                        index=idx, type=BlockType.TABLE, page=page_no, bbox=bbox,
                        ocr_conf=b.get("score"), table=_html_to_table(html),  # table conf 在块级
                    )
                )
                idx += 1
            elif btype in _BTYPE:
                text, conf = _text_and_conf(b)
                if not text:
                    continue
                blocks.append(
                    Block(
                        index=idx, type=_BTYPE[btype], text=text, page=page_no,
                        bbox=bbox, ocr_conf=conf, level=b.get("level"),
                    )
                )
                idx += 1
            # 其它 type(image/equation 等,无文本)→ 跳过
    return blocks


def _run_mineru(data: bytes, source_format: str) -> dict:
    """in-process MinerU pipeline → ``middle.json`` dict。

    ``mineru`` import 延迟于此(避免默认装载 + multiprocessing 在 import 期触发,D6);
    调用栈入口须 spawn 安全(管线 CLI / pytest 已 ``__main__`` 守护)。
    """
    from mineru.cli.common import do_parse, images_bytes_to_pdf_bytes

    pdf_bytes = images_bytes_to_pdf_bytes(data) if source_format in ("jpg", "png") else data
    with tempfile.TemporaryDirectory(prefix="mineru_") as out:
        do_parse(
            output_dir=out,
            pdf_file_names=["doc"],
            pdf_bytes_list=[pdf_bytes],
            p_lang_list=["ch"],
            backend="pipeline",
            f_dump_middle_json=True,
            f_dump_md=False,
            f_dump_model_output=False,
            f_dump_orig_pdf=False,
            f_dump_content_list=False,
            f_draw_layout_bbox=False,
            f_draw_span_bbox=False,
        )
        mjs = glob.glob(os.path.join(out, "**", "*middle.json"), recursive=True)
        if not mjs:
            raise RuntimeError("MinerU 未产出 middle.json")
        return json.loads(Path(mjs[0]).read_text(encoding="utf-8"))


class MinerUParser(ParserAdapter):
    """扫描件/图片 OCR(MinerU pipeline 后端,in-process → middle.json → IR blocks,§4.1)。

    失败(未装 / 解析异常)→ ``ParseResult(error_code=OCR_FAILED)`` 非阻断(走 s1 ``_route_failure``)。
    """

    def parse(
        self, data: bytes, source_format: str, *, scanned_char_per_page_max: int
    ) -> ParseResult:
        try:
            middle = _run_mineru(data, source_format)
        except ImportError as e:  # 未装 MinerU([ocr] extra)
            return ParseResult(
                error_code=ErrorCode.OCR_FAILED.value, reason=f"MinerU 未安装: {e}"
            )
        except Exception as e:  # noqa: BLE001 — OCR 失败非阻断
            return ParseResult(
                error_code=ErrorCode.OCR_FAILED.value, reason=f"MinerU 解析失败: {e}"
            )
        blocks = _mineru_to_blocks(middle)
        return ParseResult(
            blocks=blocks,
            page_count=len(middle.get("pdf_info", [])),
            title=(blocks[0].text[:80] if blocks else None),
        )
