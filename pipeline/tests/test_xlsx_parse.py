"""T1.5 xlsx 直读(parser 能力):openpyxl → Table IR;detect_format 识别 xlsx(但不入白名单)。

范围 = 解析层(parser 读 xlsx → Table 块)。端到端入库(白名单/s1 路由/切块 profile)受纯表格
无条款制约,**留 P2 P-MISC**(§22.3 费用数据「不走切块管线」),不在本任务。
"""

import io

from openpyxl import Workbook

from common.ir import BlockType, SourceFormat
from pipeline.parsing.light_parser import LightParser
from pipeline.stages.s0_register import WHITELIST_FORMATS, detect_format


def _xlsx_bytes(rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_source_format_has_xlsx():
    assert SourceFormat.XLSX == "xlsx"  # add-only 枚举


def test_detect_recognizes_xlsx_but_not_whitelisted():
    # detect_format 识别 xlsx(magic);端到端入库白名单留 P2(纯表格 S3 不适用)→ xlsx 不在白名单
    data = _xlsx_bytes([["费用项目", "标准"], ["差旅", "500"]])
    assert detect_format(data) == "xlsx"
    assert "xlsx" not in WHITELIST_FORMATS


def test_light_parser_xlsx_to_table_block():
    data = _xlsx_bytes([["费用项目", "标准"], ["差旅", "500"], ["招待", "300"]])
    res = LightParser().parse(data, "xlsx", scanned_char_per_page_max=50)
    assert res.ok
    tables = [b for b in res.blocks if b.type is BlockType.TABLE]
    assert len(tables) == 1
    t = tables[0].table
    assert t.n_rows == 3 and t.n_cols == 2
    assert {"费用项目", "标准", "差旅", "500"} <= {c.text for c in t.cells}
    assert "| 费用项目 | 标准 |" in t.to_markdown()  # 复用 T0.2 markdown 序列化
