"""OCR 测试共享:真跑门控 + 动态样本(非 test_ 前缀,不被 collect)。

门控对齐 BGE-M3 纪律(`PIPELINE_EMBEDDING_MODEL` + `HF_HUB_OFFLINE`,无缓存则 skip、绝不联网):
真跑须 **装了 mineru + 显式 `MINERU_REAL_TEST=1`**(已预热模型方设),否则 skip——
避免装了 [ocr] 但未预热模型时意外触发 MinerU 首跑下载。
"""

import io
import os


def mineru_ready() -> bool:
    """真跑门控:mineru 可 import + 显式 `MINERU_REAL_TEST=1`(绝不意外联网下载模型)。"""
    try:
        import mineru  # noqa: F401
    except ImportError:
        return False
    return os.environ.get("MINERU_REAL_TEST") == "1"


def ocr_png(txt: str = "OCR test 12345 line") -> bytes:
    """动态生成测试 png(仓内不存二进制;ASCII 大字体便于 OCR 识别)。"""
    from PIL import Image, ImageDraw, ImageFont

    im = Image.new("RGB", (600, 150), "white")
    try:
        font = ImageFont.load_default(size=40)
    except TypeError:  # 旧 Pillow 无 size 参数
        font = ImageFont.load_default()
    ImageDraw.Draw(im).text((20, 50), txt, fill="black", font=font)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()
