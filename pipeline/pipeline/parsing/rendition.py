"""规范渲染件:LibreOffice soffice 渲染 docx→PDF + pdfplumber 逐页文本(剥页眉页脚带)。

页码权威 = 渲染件(SPEC《页码锚点机制》)。B4 复用 ``render_pdf`` / ``page_texts``;
``spike_align`` 是 SP1 的端到端验证便利函数(渲染→取页文本→对齐→命中率)。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pdfplumber

_MAC_SOFFICE = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")


def soffice_bin() -> str:
    """定位 soffice:env PIPELINE_SOFFICE > PATH > mac .app 内(信创可经 env 指定)。"""
    env = os.environ.get("PIPELINE_SOFFICE")
    if env:
        return env
    found = shutil.which("soffice") or shutil.which("libreoffice")
    if found:
        return found
    if _MAC_SOFFICE.exists():
        return str(_MAC_SOFFICE)
    raise RuntimeError("未找到 soffice/libreoffice;请安装 LibreOffice 或设 PIPELINE_SOFFICE")


def render_pdf(src: Path, out_dir: Path, *, timeout: int = 120) -> Path:
    """soffice --headless 把 docx 渲染为 PDF,落 out_dir/<stem>.pdf,返回其路径。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [soffice_bin(), "--headless", "--convert-to", "pdf", "--outdir", str(out_dir), str(src)],
        check=True,
        timeout=timeout,
        capture_output=True,
    )
    pdf = out_dir / (Path(src).stem + ".pdf")
    if not pdf.exists():
        raise RuntimeError(f"soffice 未生成渲染件: {pdf}")
    return pdf


def page_texts(pdf_path: Path, *, header_band_pct: float, footer_band_pct: float) -> list[str]:
    """逐页正文文本:按 y 坐标裁掉顶部页眉带与底部页脚带后 extract_text。"""
    out: list[str] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            h = page.height
            body = page.crop((0, header_band_pct * h, page.width, h - footer_band_pct * h))
            out.append(body.extract_text() or "")
    return out


def spike_align(
    docx_path: Path,
    out_dir: Path,
    *,
    header_band_pct: float,
    footer_band_pct: float,
    fuzzy_threshold: float,
) -> dict:
    """SP1:docx → 渲染 → 逐页文本 → 对齐 docx 段落 → 命中率。"""
    from docx import Document

    from pipeline.parsing.page_align import align_pages

    pdf = render_pdf(Path(docx_path), Path(out_dir))
    pages = page_texts(pdf, header_band_pct=header_band_pct, footer_band_pct=footer_band_pct)
    blocks = [p.text for p in Document(str(docx_path)).paragraphs if p.text.strip()]
    spans = align_pages(blocks, pages, fuzzy_threshold=fuzzy_threshold)
    hit = sum(1 for s in spans if s[0] is not None)
    return {
        "pages": len(pages),
        "blocks": len(blocks),
        "hit": hit,
        "miss": len(blocks) - hit,
        "hit_rate": hit / max(1, len(blocks)),
        "spans": spans,
    }
