"""统一中间表示(IR)—— 解析器与下游之间的**稳定契约边界**(SPEC 对齐生产 §4.2)。

设计原则:
- IR 是解析器可替换的前提(light → DeepDoc 切换不动下游),故此 schema 为硬契约、**add-only**。
- 文档顺序由 ``Block.index`` 唯一确定(严格升序),是页码单调对齐与切块 ``seq`` 的依据。
- ``bbox`` 在 light 解析器无坐标时置 ``None``;``page`` 在文本对齐回填前为 ``None``,
  对齐未命中也为 ``None`` —— 由 QC 指标4(锚点完整率)拦截,不在 IR 层强制。
- ``extra="forbid"``:拒绝未知字段,保证契约不被悄悄扩张。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, model_validator


class SourceFormat(StrEnum):
    DOCX = "docx"
    PDF = "pdf"


class BlockType(StrEnum):
    PARAGRAPH = "paragraph"
    HEADING = "heading"
    LIST_ITEM = "list_item"
    TABLE = "table"


class BBox(BaseModel):
    """渲染件/PDF 坐标系下的包围盒(left, top, right, bottom)。light 无坐标时整体为 None。"""

    model_config = ConfigDict(extra="forbid")

    x0: float
    y0: float
    x1: float
    y1: float


class TableCell(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    row: int
    col: int
    rowspan: int = 1
    colspan: int = 1


class Table(BaseModel):
    """表格块内容。``header_rows`` 为重复表头行数(切块按行组拆时复用,见 S3 切块六规则)。"""

    model_config = ConfigDict(extra="forbid")

    n_rows: int
    n_cols: int
    cells: list[TableCell]
    header_rows: int = 1

    def expanded_rows(self) -> list[list[str]]:
        """合并单元格展开:rowspan/colspan 覆盖的格补该格文本;空位补 ""(供切块/markdown)。"""
        grid: dict[tuple[int, int], str] = {}
        for c in self.cells:
            for dr in range(c.rowspan):
                for dc in range(c.colspan):
                    grid.setdefault((c.row + dr, c.col + dc), c.text)
        return [[grid.get((r, col), "") for col in range(self.n_cols)] for r in range(self.n_rows)]

    def to_markdown(self) -> str:
        """渲染 markdown 表(合并单元格展开 + 表头分隔行)。供切块表格块 / 表格摘要消费。"""
        lines = ["| " + " | ".join(r) + " |" for r in self.expanded_rows()]
        if self.n_rows and self.n_cols:
            sep = "| " + " | ".join("---" for _ in range(self.n_cols)) + " |"
            hr = max(1, self.header_rows)
            lines = lines[:hr] + [sep] + lines[hr:]
        return "\n".join(lines)


class Block(BaseModel):
    """文档顺序中的一个内容块。表格块文本置空,内容在 ``table``;其余块 ``table`` 为 None。"""

    model_config = ConfigDict(extra="forbid")

    index: int  # 文档序(0-based,严格升序):单调对齐与 seq 的根据
    type: BlockType
    level: int | None = None  # 标题层级(heading 时;生产 §4.2)。light 按样式推断,无则 None
    text: str = ""  # 表格块为空
    page: int | None = None  # page_start;对齐回填前/未命中为 None
    page_end: int | None = None  # 跨页块的结束页;不跨页时 None(== page)
    bbox: BBox | None = None  # light 无坐标时 None
    ocr_conf: float | None = None  # 块级 OCR 置信度(仅 OCR 文档;参与质检指标6,§5.1;非 OCR 为 None)
    style: str | None = None  # 解析器原生样式名(如 docx 段落样式),辅助结构识别
    table: Table | None = None  # type==TABLE 时非空

    @model_validator(mode="after")
    def _check_invariants(self) -> Block:
        if self.type == BlockType.TABLE and self.table is None:
            raise ValueError("TABLE 块必须携带 table")
        if self.type != BlockType.TABLE and self.table is not None:
            raise ValueError(f"{self.type.value} 块不应携带 table")
        if self.page_end is not None and self.page is None:
            raise ValueError("有 page_end 必须先有 page")
        if self.page is not None and self.page_end is not None and self.page_end < self.page:
            raise ValueError("page_end 不得小于 page")
        return self


class IRDocument(BaseModel):
    """单文档 IR。落 ObjectStore ``ir/{doc_version_id}.json``。"""

    model_config = ConfigDict(extra="forbid")

    doc_version_id: str
    source_format: SourceFormat
    page_count: int | None = None  # 渲染件/原 PDF 页数
    title: str | None = None
    blocks: list[Block]

    @model_validator(mode="after")
    def _check_order(self) -> IRDocument:
        idxs = [b.index for b in self.blocks]
        if any(b <= a for a, b in zip(idxs, idxs[1:], strict=False)):
            raise ValueError("blocks 的 index 必须严格升序且唯一")
        return self
