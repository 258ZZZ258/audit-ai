"""T0.2:IR Block.ocr_conf add-only(块级 OCR 置信度,参与质检指标6);默认 None 不破契约。"""

from common.ir import Block, BlockType, IRDocument, SourceFormat


def test_block_accepts_ocr_conf():
    b = Block(index=0, type=BlockType.PARAGRAPH, text="第一条", page=1, ocr_conf=0.97)
    assert b.ocr_conf == 0.97


def test_ocr_conf_defaults_none():
    b = Block(index=0, type=BlockType.PARAGRAPH, text="x")
    assert b.ocr_conf is None


def test_irdocument_validates_with_ocr_conf():
    doc = IRDocument(
        doc_version_id="dv",
        source_format=SourceFormat.PDF,
        blocks=[Block(index=0, type=BlockType.PARAGRAPH, text="a", page=1, ocr_conf=0.9)],
    )
    assert doc.blocks[0].ocr_conf == 0.9
