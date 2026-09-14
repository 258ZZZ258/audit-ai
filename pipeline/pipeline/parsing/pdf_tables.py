"""Ruled PDF tables -> existing IR cells, preserving surrounding page text.

Only geometrically closed tables are accepted. Uncertain detections stay in the
ordinary text path; continuation rows are never discarded as assumed headers.
"""

import re

from common.ir import Block, BlockType, Table, TableCell
from pipeline.chunking.normalize import normalize_radicals


def cell_text(text):
    text = normalize_radicals(text)
    # PDF layout wraps are not semantic new paragraphs inside a cell. Preserve
    # English word separation; CJK layout lines and split bond codes concatenate.
    text = re.sub(r"(?<=[a-zA-Z])\n(?=[a-zA-Z])", " ", text)
    return text.replace("\n", "")


def inside(obj, bbox):
    x, y = (obj["x0"] + obj["x1"]) / 2, (obj["top"] + obj["bottom"]) / 2
    return bbox[0] <= x < bbox[2] and bbox[1] <= y < bbox[3]


def as_ir_table(found, chars):
    rows = found.extract()
    if len(rows) < 2 or len(rows[0]) < 2:
        return None
    geometries = [cell for row in found.rows for cell in row.cells if cell is not None]
    if any(
        inside(char, found.bbox) and not any(inside(char, cell) for cell in geometries)
        for char in chars if char.get("text", "").strip()
    ):
        return None  # Never remove unaccounted text inside a detected bounding box.
    cells = []
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            if value is None:
                continue
            bbox = found.rows[r].cells[c]
            rowspan, colspan = 1, 1
            while r + rowspan < len(rows) and found.rows[r + rowspan].bbox[1] < bbox[3] - .1:
                rowspan += 1
            while c + colspan < len(row) and found.columns[c + colspan].bbox[0] < bbox[2] - .1:
                colspan += 1
            cells.append(TableCell(row=r, col=c, rowspan=rowspan, colspan=colspan,
                                   text=cell_text(value)))
    # Require explicit labels, not position, to suppress a header row. On a
    # continuation page the first row may still be business data.
    labels = {"序号", "问题摘要", "整改情况", "事项概述及类型", "查询索引", "责任部门", "涉及单位"}
    header = int(sum(cell_text(value or "").strip() in labels for value in rows[0]) >= 2)
    return Table(n_rows=len(rows), n_cols=len(rows[0]), cells=cells, header_rows=header)


def page_blocks(page, page_number, start_index):
    accepted = []
    for found in page.find_tables():
        table = as_ir_table(found, page.chars)
        if table is not None:
            # Overlapping detections cannot both own the same text.
            overlap = any(
                min(found.bbox[2], old.bbox[2]) > max(found.bbox[0], old.bbox[0])
                and min(found.bbox[3], old.bbox[3]) > max(found.bbox[1], old.bbox[1])
                for old, _ in accepted
            )
            if not overlap:
                accepted.append((found, table))
    if not accepted:
        return [Block(index=start_index+i, type=BlockType.PARAGRAPH, text=line, page=page_number)
                for i, line in enumerate(
                    line for line in normalize_radicals(page.extract_text() or "").split("\n")
                    if line.strip())]
    outside = page.filter(lambda obj: not any(inside(obj, t.bbox) for t, _ in accepted)
                          if obj.get("object_type") == "char" else True)
    events = [(line["top"], line["x0"], BlockType.PARAGRAPH,
               normalize_radicals(line["text"])) for line in outside.extract_text_lines()]
    events.extend((found.bbox[1], found.bbox[0], BlockType.TABLE, table)
                  for found, table in accepted)
    blocks = []
    for _, _, kind, content in sorted(events, key=lambda event: event[:2]):
        kwargs = {"table": content} if kind == BlockType.TABLE else {"text": content}
        blocks.append(Block(index=start_index+len(blocks), type=kind, page=page_number, **kwargs))
    return blocks
