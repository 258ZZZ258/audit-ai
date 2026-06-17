"""ParserAdapter:解析器可替换边界(light / DeepDoc)。输出 IR blocks,下游不感知后端。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from common.ir import Block


@dataclass
class ParseResult:
    """解析产物;``error_code`` 非空表示未成功(隔离/失败,如扫描件 E202 / 白名单外 E101)。"""

    blocks: list[Block] = field(default_factory=list)
    page_count: int | None = None
    title: str | None = None
    error_code: str | None = None
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.error_code is None


class ParserAdapter(ABC):
    @abstractmethod
    def parse(
        self, data: bytes, source_format: str, *, scanned_char_per_page_max: int
    ) -> ParseResult:
        """把原件字节解析为 IR blocks;docx 的 page 暂置 None(待文本对齐回填)。"""
        ...
