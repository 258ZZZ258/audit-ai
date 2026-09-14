import io

import pytest

from pipeline.parsing.light_parser import LightParser
from pipeline.parsing.ocr_model_path import ascii_model_copy


def pdf_with_image(size):
    canvas = pytest.importorskip("reportlab.pdfgen.canvas")
    from PIL import Image
    from reportlab.lib.utils import ImageReader

    stream = io.BytesIO()
    pdf = canvas.Canvas(stream, pagesize=(400, 500))
    pdf.drawImage(ImageReader(Image.new("RGB", (40, 50), "white")), 0, 0,
                  width=size[0], height=size[1])
    pdf.drawString(20, 450, "Old OCR text is present but may be wrong " * 2)
    pdf.save()
    return stream.getvalue()


def test_full_page_scan_with_text_layer_requests_ocr_but_logo_does_not():
    scan = LightParser().parse(pdf_with_image((400, 500)), "pdf", scanned_char_per_page_max=30)
    assert not scan.ok and scan.error_code == "E202-DEMO"
    assert "文字层" in scan.reason
    native = LightParser().parse(pdf_with_image((40, 50)), "pdf", scanned_char_per_page_max=30)
    assert native.ok


def test_model_cache_copy_is_exact_reusable_and_repairs_corrupt_copy(tmp_path):
    source = tmp_path / "中文模型.ftz"
    source.write_bytes(b"model-weights")
    cache = tmp_path / "ascii-cache"
    copied = ascii_model_copy(source, cache)
    assert copied.read_bytes() == source.read_bytes()
    assert ascii_model_copy(source, cache) == copied
    copied.write_bytes(b"corrupted")
    assert ascii_model_copy(source, cache).read_bytes() == source.read_bytes()
