"""归一化:中文数字 → int,条款号 → 规范形,全角/空白处理。

条款号规范形约定(进入 clause_path_norm,是 chunk_id 的输入,必须确定):
- 普通条:Arabic 字符串,如 ``"二十一" → "21"``、``"21" → "21"``
- 插入条:``"<base>-<insert>"``,统一中/西/小数式三种写法:
  ``"二十一之一" / "21之一" / "21bis" / "21.1b" → "21-1"``

应对真实素材的逐字加空格 / 全角(如 226 号 PDF 的 "第 一 条"):先 ``to_halfwidth`` + ``strip_ws``。
"""

from __future__ import annotations

import re

_DIGITS = {
    "〇": 0,
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_UNITS = {"十": 10, "百": 100, "千": 1000}
_CN = "".join(_DIGITS) + "".join(_UNITS)
_LATIN_INSERT = {"bis": 1, "ter": 2, "quater": 3, "quinquies": 4}


def to_halfwidth(s: str) -> str:
    """全角 ASCII / 全角空格 → 半角。"""
    out = []
    for ch in s:
        o = ord(ch)
        if o == 0x3000:
            out.append(" ")
        elif 0xFF01 <= o <= 0xFF5E:
            out.append(chr(o - 0xFEE0))
        else:
            out.append(ch)
    return "".join(out)


def strip_ws(s: str) -> str:
    """去掉所有空白(含逐字加空格的排版)。"""
    return re.sub(r"\s+", "", s)


def cn_to_int(s: str) -> int:
    """中文数字 → int(支持 十/百/千、零/〇、两;Arabic 直接透传)。"""
    s = strip_ws(to_halfwidth(s))
    if s.isdigit():
        return int(s)
    if not s:
        raise ValueError("空数字串")
    section = 0
    number = 0
    for ch in s:
        if ch in _DIGITS:
            number = _DIGITS[ch]
        elif ch in _UNITS:
            section += (number or 1) * _UNITS[ch]
            number = 0
        else:
            raise ValueError(f"非中文数字字符: {ch!r}")
    return section + number


def normalize_clause_no(raw: str) -> str:
    """条款号(第 X 条 的 X 部分)→ 规范形 ``"N"`` 或 ``"N-K"``(插入条)。"""
    s = strip_ws(to_halfwidth(raw))
    if not s:
        raise ValueError("空 clause 号")

    # 中文(+ 之N)
    m = re.fullmatch(rf"([{_CN}]+)(?:之([{_CN}\d]+))?", s)
    if m:
        base = cn_to_int(m.group(1))
        return f"{base}-{cn_to_int(m.group(2))}" if m.group(2) else str(base)

    # Arabic(+ 之N)
    m = re.fullmatch(rf"(\d+)(?:之([{_CN}\d]+))?", s)
    if m:
        base = int(m.group(1))
        return f"{base}-{cn_to_int(m.group(2))}" if m.group(2) else str(base)

    # 西文 bis/ter/quater/quinquies
    m = re.fullmatch(r"(\d+)(bis|ter|quater|quinquies)", s, re.IGNORECASE)
    if m:
        return f"{int(m.group(1))}-{_LATIN_INSERT[m.group(2).lower()]}"

    # 小数式 21.1b
    m = re.fullmatch(r"(\d+)\.(\d+)[a-zA-Z]?", s)
    if m:
        return f"{int(m.group(1))}-{int(m.group(2))}"

    raise ValueError(f"无法归一化 clause 号: {raw!r}")
