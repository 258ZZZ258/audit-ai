"""T1 `_mineru_to_blocks` 映射(spike middle.json fixture,无 MinerU)+ T2 MinerUParser(门控)。"""

import json
from pathlib import Path

import pytest
from _ocr_gate import mineru_ready, ocr_png

from common.ir import BlockType, IRDocument
from pipeline.parsing.mineru_parser import _mineru_to_blocks

FIX = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def test_map_toc_text_block():
    blocks = _mineru_to_blocks(_load("mineru_middle_toc.json"))
    assert len(blocks) == 1  # 目录 = 1 个 index block(27 行 span)
    b = blocks[0]
    assert b.type == BlockType.PARAGRAPH and b.page == 1
    assert "多意图拆分" in b.text and b.ocr_conf is not None


def test_map_ocr_conf_is_min_of_spans():
    middle = {"pdf_info": [{"page_idx": 0, "para_blocks": [{
        "type": "text", "bbox": [0, 0, 1, 1],
        "lines": [{"spans": [{"content": "A", "score": 0.9}, {"content": "B", "score": 0.5}]}],
    }]}]}
    b = _mineru_to_blocks(middle)[0]
    assert b.ocr_conf == 0.5 and b.text == "AB"  # min(0.9, 0.5)


def test_map_table_block():
    blocks = _mineru_to_blocks(_load("mineru_middle_table.json"))
    tables = [b for b in blocks if b.type == BlockType.TABLE]
    assert len(tables) == 1
    t = tables[0].table
    assert t.n_cols == 7 and "代客理财" in t.to_markdown()
    assert tables[0].ocr_conf is not None


def test_map_title_and_page():
    blocks = _mineru_to_blocks(_load("mineru_middle_table.json"))
    assert blocks[0].type == BlockType.HEADING and "业务判断分层" in blocks[0].text
    assert all(b.page == 1 for b in blocks)


def test_map_index_strictly_increasing():
    for name in ("mineru_middle_toc.json", "mineru_middle_table.json"):
        idxs = [b.index for b in _mineru_to_blocks(_load(name))]
        assert idxs == list(range(len(idxs)))


def test_map_constructs_irdocument():
    blocks = _mineru_to_blocks(_load("mineru_middle_table.json"))
    doc = IRDocument(doc_version_id="x", source_format="pdf", blocks=blocks)
    assert len(doc.blocks) == len(blocks)  # 过 _check_order 升序校验


def test_map_table_rowspan_colspan():
    middle = {"pdf_info": [{"page_idx": 0, "para_blocks": [{
        "type": "table", "bbox": [0, 0, 1, 1], "score": 0.95,
        "blocks": [{"lines": [{"spans": [{
            "type": "table", "score": 0.95,
            "html": "<table><tr><td rowspan=2>A</td><td>B</td></tr><tr><td>C</td></tr></table>",
        }]}]}],
    }]}]}
    b = _mineru_to_blocks(middle)[0]
    assert b.type == BlockType.TABLE
    cells = {(c.row, c.col): c for c in b.table.cells}
    assert cells[(0, 0)].text == "A" and cells[(0, 0)].rowspan == 2
    assert cells[(0, 1)].text == "B" and cells[(1, 1)].text == "C"  # C 避开 A 的 rowspan


# ── T2 MinerUParser:流程(monkeypatch _run_mineru)+ 真跑(门控 _ocr_gate.mineru_ready)──────
def test_parse_maps_via_run_mineru(monkeypatch):
    from pipeline.parsing import mineru_parser as mp

    middle = _load("mineru_middle_table.json")
    monkeypatch.setattr(mp, "_run_mineru", lambda data, fmt: middle)
    res = mp.MinerUParser().parse(b"fakeimg", "png", scanned_char_per_page_max=50)
    assert res.ok and res.blocks
    assert any(b.type == BlockType.TABLE for b in res.blocks)
    assert any(b.ocr_conf is not None for b in res.blocks)


def test_parse_failure_returns_ocr_failed(monkeypatch):
    from pipeline.parsing import mineru_parser as mp
    from pipeline.states import ErrorCode

    def _boom(data, fmt):
        raise RuntimeError("boom")

    monkeypatch.setattr(mp, "_run_mineru", _boom)
    res = mp.MinerUParser().parse(b"x", "png", scanned_char_per_page_max=50)
    assert not res.ok and res.error_code == ErrorCode.OCR_FAILED.value


@pytest.mark.skipif(not mineru_ready(), reason="MinerU 真跑未启用(需 mineru + MINERU_REAL_TEST=1)")
def test_parse_real_mineru_image():
    from pipeline.parsing.mineru_parser import MinerUParser

    res = MinerUParser().parse(ocr_png(), "png", scanned_char_per_page_max=50)
    assert res.ok  # in-process do_parse 不崩,产 ParseResult
    if res.blocks:  # OCR 识别出块时带 ocr_conf(质量 spike 已验,此处只验链路)
        assert any(b.ocr_conf is not None for b in res.blocks)
