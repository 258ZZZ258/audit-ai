import pytest
from pydantic import ValidationError

from common.ir import (
    BBox,
    Block,
    BlockType,
    IRDocument,
    SourceFormat,
    Table,
    TableCell,
)


def _sample_doc() -> IRDocument:
    return IRDocument(
        doc_version_id="01HVZ...demo",
        source_format=SourceFormat.DOCX,
        page_count=3,
        title="XX 费用报销管理办法",
        blocks=[
            Block(index=0, type=BlockType.HEADING, text="第一章 总则", page=1, style="Heading 1"),
            Block(
                index=1,
                type=BlockType.PARAGRAPH,
                text="第一条 为了规范……",
                page=1,
                page_end=2,  # 跨页条文
                bbox=BBox(x0=72.0, y0=120.0, x1=523.0, y1=140.0),
            ),
            Block(index=2, type=BlockType.PARAGRAPH, text="第二条 ……"),  # page 对齐前为 None
            Block(
                index=3,
                type=BlockType.TABLE,
                page=2,
                table=Table(
                    n_rows=2,
                    n_cols=2,
                    header_rows=1,
                    cells=[
                        TableCell(text="审批层级", row=0, col=0),
                        TableCell(text="权限", row=0, col=1),
                        TableCell(text="部门经理", row=1, col=0),
                        TableCell(text="≤1万", row=1, col=1),
                    ],
                ),
            ),
        ],
    )


def test_ir_roundtrip_lossless():
    doc = _sample_doc()
    restored = IRDocument.model_validate_json(doc.model_dump_json())
    assert restored == doc
    # 可空字段如实保留
    assert restored.blocks[2].page is None
    assert restored.blocks[0].bbox is None
    assert restored.blocks[1].page_end == 2


def test_table_block_requires_table():
    with pytest.raises(ValidationError):
        Block(index=0, type=BlockType.TABLE, text="x")  # 缺 table


def test_non_table_block_rejects_table():
    tbl = Table(n_rows=1, n_cols=1, cells=[TableCell(text="a", row=0, col=0)])
    with pytest.raises(ValidationError):
        Block(index=0, type=BlockType.PARAGRAPH, text="x", table=tbl)


def test_page_end_consistency():
    with pytest.raises(ValidationError):
        Block(index=0, type=BlockType.PARAGRAPH, text="x", page=5, page_end=3)
    with pytest.raises(ValidationError):
        Block(index=0, type=BlockType.PARAGRAPH, text="x", page_end=2)  # 有 end 无 start


def test_blocks_must_be_strictly_ordered():
    with pytest.raises(ValidationError):
        IRDocument(
            doc_version_id="d",
            source_format=SourceFormat.PDF,
            blocks=[
                Block(index=0, type=BlockType.PARAGRAPH, text="a"),
                Block(index=0, type=BlockType.PARAGRAPH, text="b"),  # 重复 index
            ],
        )


def test_extra_field_forbidden():
    with pytest.raises(ValidationError):
        Block(index=0, type=BlockType.PARAGRAPH, text="x", bogus=1)
