"""页码回填:把 IR block 对齐到规范渲染件,得到 page_start/page_end(SPEC《页码锚点机制》)。

- 渲染件逐页文本归一化后拼成全文,记录每页字符偏移区间。
- 对每个 block 按文档序做**单调两指针**精确子串匹配(从上次命中位置向后查):
  既 O(n),又天然消解重复文本歧义(如多处"第X条 删除")。
- 精确未中 → 局部窗口 ``rapidfuzz`` 模糊兜底(阈值入参);仍未中 → page 置 None,
  交 QC 指标4 拦截。
- 归一化函数对 block 文本与渲染件文本**对称施用**(对齐成立的前提)。
"""

from __future__ import annotations

from rapidfuzz import fuzz

from pipeline.chunking.normalize import strip_ws, to_halfwidth
from pipeline.ir import Block


def normalize_for_align(s: str) -> str:
    """对齐用归一化:全半角统一 + 去所有空白。两侧对称施用。"""
    return strip_ws(to_halfwidth(s))


def build_page_index(page_texts: list[str]) -> tuple[str, list[tuple[int, int]]]:
    """逐页归一化 → 拼全文 + 每页在全文中的 [start, end) 偏移区间。"""
    full_parts: list[str] = []
    offsets: list[tuple[int, int]] = []
    pos = 0
    for p in page_texts:
        np_ = normalize_for_align(p)
        offsets.append((pos, pos + len(np_)))
        full_parts.append(np_)
        pos += len(np_)
    return "".join(full_parts), offsets


def page_of_offset(offsets: list[tuple[int, int]], off: int) -> int | None:
    """全文偏移 → 页号(1-based)。"""
    for i, (s, e) in enumerate(offsets):
        if s <= off < e:
            return i + 1
    if offsets and off >= offsets[-1][1]:  # 末尾边界归末页
        return len(offsets)
    return None


def _fuzzy_find(full: str, needle: str, cursor: int, threshold: float) -> int | None:
    """从 cursor 起的局部窗口内模糊定位 needle,返回全文偏移或 None。"""
    window_end = min(len(full), cursor + max(len(needle) * 4, 500))
    window = full[cursor:window_end]
    if not window:
        return None
    al = fuzz.partial_ratio_alignment(needle, window)
    if al is None or al.score < threshold:
        return None
    return cursor + al.dest_start


def align_pages(
    block_texts: list[str], page_texts: list[str], *, fuzzy_threshold: float
) -> list[tuple[int | None, int | None]]:
    """返回每个 block 的 (page_start, page_end);未中为 (None, None)。"""
    full, offsets = build_page_index(page_texts)
    cursor = 0
    spans: list[tuple[int | None, int | None]] = []
    for bt in block_texts:
        nb = normalize_for_align(bt)
        if not nb:
            spans.append((None, None))
            continue
        idx = full.find(nb, cursor)
        if idx == -1:
            fz = _fuzzy_find(full, nb, cursor, fuzzy_threshold)
            idx = fz if fz is not None else -1
        if idx < 0:
            spans.append((None, None))
            continue
        start = page_of_offset(offsets, idx)
        end = page_of_offset(offsets, idx + len(nb) - 1)
        spans.append((start, end))
        cursor = idx + len(nb)
    return spans


def align_blocks(
    blocks: list[Block], page_texts: list[str], *, fuzzy_threshold: float
) -> list[Block]:
    """回填 page/page_end 到有文本的 block(空文本块如表格保持不变,由解析器给页)。"""
    spans = align_pages([b.text for b in blocks], page_texts, fuzzy_threshold=fuzzy_threshold)
    out: list[Block] = []
    for b, (ps, pe) in zip(blocks, spans, strict=True):
        if not b.text.strip():
            out.append(b)
            continue
        page_end = pe if (pe is not None and pe != ps) else None
        out.append(b.model_copy(update={"page": ps, "page_end": page_end}))
    return out
