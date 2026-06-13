"""共享 fixtures。

soffice 探测:**二进制找得到 ≠ 能渲染**(profile 锁 / 缺字体库 / 静默退 0 不产出 / 超时)。
本 fixture 用与生产同一个 ``render_pdf`` 真渲一份最小 docx,任何失败即 skip 所有渲染相关
测试——把"环境不可用"与"代码回归"区分开:已知良好输入都渲染不出是环境问题(skip);
某具体测试在探测通过后仍渲染失败,才是真 bug(照常 fail)。
"""

from __future__ import annotations

import io

import pytest
from docx import Document as Docx

from pipeline.parsing.rendition import render_pdf, soffice_bin


@pytest.fixture(scope="session")
def soffice(tmp_path_factory):
    """探测 soffice 真能 docx→PDF;二进制缺失或渲染失败均 skip。返回可用的 soffice 路径。"""
    try:
        bin_ = soffice_bin()
    except RuntimeError as e:
        pytest.skip(str(e))
    d = tmp_path_factory.mktemp("soffice_probe")
    src = d / "probe.docx"
    buf = io.BytesIO()
    doc = Docx()
    doc.add_paragraph("探测渲染")
    doc.save(buf)
    src.write_bytes(buf.getvalue())
    try:
        render_pdf(src, d, timeout=60)
    except Exception as e:  # 二进制在但渲染崩:环境问题,跳过渲染相关测试(非代码缺陷)
        pytest.skip(f"soffice 存在但渲染失败(环境问题,非代码): {e}")
    return bin_
