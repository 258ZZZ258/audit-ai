"""T4 make_ocr_parser(PIPELINE_OCR_BACKEND)+ T5 s1 路由 / 白名单 / detect_format。"""

from types import SimpleNamespace

import pytest

from common.ir import Block, BlockType, SourceFormat
from pipeline.parsing.adapter import ParseResult
from pipeline.parsing.factory import make_ocr_parser
from pipeline.parsing.mineru_parser import MinerUParser
from pipeline.stage_base import StageResult
from pipeline.stages.s0_register import WHITELIST_FORMATS, detect_format
from pipeline.states import ErrorCode, PipelineState


def test_ocr_backend_default_none(monkeypatch):
    monkeypatch.delenv("PIPELINE_OCR_BACKEND", raising=False)
    assert make_ocr_parser() is None  # 默认 OCR 关(向后兼容)


def test_ocr_backend_mineru(monkeypatch):
    monkeypatch.setenv("PIPELINE_OCR_BACKEND", "mineru")
    assert isinstance(make_ocr_parser(), MinerUParser)


def test_ocr_backend_unknown_raises(monkeypatch):
    monkeypatch.setenv("PIPELINE_OCR_BACKEND", "bogus")
    with pytest.raises(ValueError, match="PIPELINE_OCR_BACKEND"):
        make_ocr_parser()


# ── T5 detect_format / 白名单 / SourceFormat(纯)──────────────────────────────
def test_detect_format_png():
    assert detect_format(b"\x89PNG\r\n\x1a\n" + b"x" * 20) == "png"


def test_detect_format_jpg():
    assert detect_format(b"\xff\xd8\xff\xe0" + b"x" * 20) == "jpg"


def test_detect_format_pdf_unchanged():
    assert detect_format(b"%PDF-1.7\nrest") == "pdf"


def test_whitelist_includes_images():
    assert {"jpg", "png"} <= WHITELIST_FORMATS


def test_sourceformat_has_jpg_png():
    assert SourceFormat("jpg") is SourceFormat.JPG and SourceFormat("png") is SourceFormat.PNG


# ── T5 s1 路由(fake ctx + monkeypatch make_ocr_parser/_ir_to_qc)──────────────
def _fake_ctx():
    parse = SimpleNamespace(scanned_char_per_page_max=50)
    return SimpleNamespace(config=SimpleNamespace(parse=parse))


class _FakeOCR:
    def parse(self, data, fmt, *, scanned_char_per_page_max):
        return ParseResult(
            blocks=[Block(index=0, type=BlockType.PARAGRAPH, text="x", ocr_conf=0.9)],
            page_count=1, title="x",
        )


class _ScannedLight:
    def parse(self, data, fmt, *, scanned_char_per_page_max):
        return ParseResult(error_code=ErrorCode.SCANNED_OCR_DISABLED.value, reason="扫描件")


def _stub_qc(monkeypatch):
    from pipeline.stages import s1_parse

    monkeypatch.setattr(
        s1_parse, "_ir_to_qc",
        lambda ctx, dvid, res, fmt: StageResult(next_state=PipelineState.QC_PENDING),
    )


def test_image_routes_to_ocr_when_enabled(monkeypatch):
    from pipeline.stages import s1_parse

    monkeypatch.setattr(s1_parse, "make_ocr_parser", lambda: _FakeOCR())
    _stub_qc(monkeypatch)
    r = s1_parse._parse_image(_fake_ctx(), "x", b"img", "png")
    assert r.next_state == PipelineState.QC_PENDING


def test_image_quarantine_when_ocr_off(monkeypatch):
    from pipeline.stages import s1_parse

    monkeypatch.setattr(s1_parse, "make_ocr_parser", lambda: None)
    r = s1_parse._parse_image(_fake_ctx(), "x", b"img", "png")
    assert r.next_state == PipelineState.QUARANTINED
    assert r.error_code == ErrorCode.SCANNED_OCR_DISABLED.value


def test_pdf_scanned_routes_to_ocr_when_enabled(monkeypatch):
    from pipeline.stages import s1_parse

    monkeypatch.setattr(s1_parse, "make_parser", lambda: _ScannedLight())
    monkeypatch.setattr(s1_parse, "make_ocr_parser", lambda: _FakeOCR())
    _stub_qc(monkeypatch)
    r = s1_parse._parse_pdf(_fake_ctx(), "x", b"pdfbytes")
    assert r.next_state == PipelineState.QC_PENDING  # 扫描件 → OCR 旁路成功


def test_pdf_scanned_quarantine_when_ocr_off(monkeypatch):
    from pipeline.stages import s1_parse

    monkeypatch.setattr(s1_parse, "make_parser", lambda: _ScannedLight())
    monkeypatch.setattr(s1_parse, "make_ocr_parser", lambda: None)  # OCR 关 → 维持 E202
    r = s1_parse._parse_pdf(_fake_ctx(), "x", b"pdfbytes")
    assert r.next_state == PipelineState.QUARANTINED
    assert r.error_code == ErrorCode.SCANNED_OCR_DISABLED.value
