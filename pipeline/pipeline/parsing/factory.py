"""解析器接缝工厂:demo = light;生产 = DeepDoc(全要素)+ MinerU(兜底)+ PaddleOCR(OCR)。

§4.1 生产解析路由:docx/pdf → DeepDoc;pdf 无文本层/图片 → PaddleOCR(GPU)→ 版面重建 →
DeepDoc 后处理;复杂版式解析失败 → MinerU 重试一次。demo 仅 light(python-docx + pdfplumber)。
本工厂经配置(``PIPELINE_PARSER_BACKEND``,默认 light)选后端;``ParserAdapter`` 是可替换边界
(IR blocks 输出,下游不感知后端),生产实现本次留 stub。
"""

from __future__ import annotations

import os

from pipeline.parsing.adapter import ParserAdapter, ParseResult
from pipeline.parsing.light_parser import LightParser
from pipeline.parsing.mineru_parser import MinerUParser  # 真实现(mineru import 延迟到 parse 内)


class _StubParser(ParserAdapter):
    """生产解析器占位基类:parse() 即抛 NotImplementedError + 再集成触发条件。"""

    _NAME = "?"
    _TRIGGER = "?"

    def parse(
        self, data: bytes, source_format: str, *, scanned_char_per_page_max: int
    ) -> ParseResult:
        raise NotImplementedError(
            f"{self._NAME} 解析器未实现(生产解析栈,属未来 CP)。再集成触发:{self._TRIGGER}。"
            "当前请用 PIPELINE_PARSER_BACKEND=light(默认)。"
        )


class DeepDocParser(_StubParser):
    """生产主解析通道(§4.1,RAGFlow DeepDoc 全要素 office/pdf 通道)。

    再集成触发:真实 PDF 需全要素版面/表格还原,且 **parser-swap 后 mini golden set 仍 F1=1.0**
    (M2 准入门)。注:走查证明当前痛点在 clause_tree(IR 边界下游),换解析器不解决 → demo 阶段留 light。
    """

    _NAME = "DeepDoc"
    _TRIGGER = "需全要素解析 + parser-swap 后 mini golden set F1=1.0(M2 准入门)"


class PaddleOCRParser(_StubParser):
    """扫描件/图片 OCR 通道(§4.1:pdf 无文本层/图片 → PaddleOCR(GPU)→ 版面重建 → DeepDoc 后处理)。

    再集成触发:需支持扫描件/图片入库(当前 <50 字/页 判扫描件 → E202-DEMO 隔离),
    且 GPU + PaddleOCR 在信创环境可部署。
    """

    _NAME = "PaddleOCR"
    _TRIGGER = "需扫描件/图片 OCR + GPU/PaddleOCR 信创可部署"


_BACKENDS: dict[str, type[ParserAdapter]] = {
    "light": LightParser,
    "deepdoc": DeepDocParser,
    "mineru": MinerUParser,
    "paddleocr": PaddleOCRParser,
}


def make_parser() -> ParserAdapter:
    """按 ``PIPELINE_PARSER_BACKEND``(默认 ``light``)返回解析器实现(默认 = demo)。"""
    backend = os.environ.get("PIPELINE_PARSER_BACKEND", "light")
    if backend not in _BACKENDS:
        raise ValueError(
            f"未知 PIPELINE_PARSER_BACKEND: {backend!r}({' | '.join(_BACKENDS)})"
        )
    return _BACKENDS[backend]()


# OCR 旁路后端(与 make_parser 分离:文本路径 light 不变,OCR 显式开启)
_OCR_BACKENDS: dict[str, type[ParserAdapter]] = {"mineru": MinerUParser}


def make_ocr_parser() -> ParserAdapter | None:
    """按 ``PIPELINE_OCR_BACKEND``(默认 ``none``)返回 OCR 解析器。

    ``none`` → None(OCR 关,扫描件仍 E202,向后兼容);``mineru`` → MinerUParser。
    """
    backend = os.environ.get("PIPELINE_OCR_BACKEND", "none")
    if backend == "none":
        return None
    if backend not in _OCR_BACKENDS:
        raise ValueError(
            f"未知 PIPELINE_OCR_BACKEND: {backend!r}(none | {' | '.join(_OCR_BACKENDS)})"
        )
    return _OCR_BACKENDS[backend]()
