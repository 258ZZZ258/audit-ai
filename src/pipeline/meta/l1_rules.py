"""L1 规则元数据抽取 + 与 manifest 交叉校验(纯逻辑,无 PG / 无 LLM)。

抽 发文字号 / 成文日期 / 发文机关(字典)/ 标题,与 manifest(DocVersion)权威值比对:
**L1 抽到候选 且 manifest 非空值(归一后)不在候选中 → 冲突**(由 s4 入 meta_confirm 队列)。
L1 没抽到 / manifest 为空 → 不算冲突(manifest 为准)。

定位约定:发文字号 / 发文机关在版头(前 ``HEAD_BLOCKS`` 块)抽;成文日期扫全文(落款常在文末)。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from pipeline.chunking.normalize import strip_ws, to_halfwidth
from pipeline.ir import IRDocument

HEAD_BLOCKS = 8

_DOC_NUM_PATTERNS = [
    re.compile(r"[一-鿿A-Za-z]{1,12}[〔\[]\d{4}[〕\]]\d+号"),  # 京证监〔2024〕5号
    re.compile(r"第\d+号"),  # 令第182号 / 第182号
]
_DATE_CN = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")
_DATE_ISO = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")


@dataclass(frozen=True)
class L1Meta:
    doc_numbers: tuple[str, ...]
    dates: tuple[date, ...]
    issuer_codes: tuple[str, ...]
    title: str | None


@dataclass(frozen=True)
class Conflict:
    field: str
    manifest: str  # manifest 权威值
    extracted: str  # L1 抽取候选(多个用 / 连)


def _norm(s: str | None) -> str:
    return strip_ws(to_halfwidth(s or ""))


def _norm_dn(s: str | None) -> str:
    """发文字号归一:在 _norm 基础上统一中西括号变体(〔【→[、〕】→])。"""
    return _norm(s).replace("〔", "[").replace("【", "[").replace("〕", "]").replace("】", "]")


def _safe_date(y: str, m: str, d: str) -> date | None:
    try:
        return date(int(y), int(m), int(d))
    except ValueError:
        return None


def extract(ir: IRDocument, issuers: list[tuple[str, str]]) -> L1Meta:
    """从 IR 抽 L1 元数据。``issuers``: ``[(code, name), ...]``(发文机关字典)。

    文号/日期**逐块**匹配(归一会删块内空白,跨块拼接会让文号正则的机构前缀贪婪吃进相邻块如标题);
    机构用版头合并文本 substring(机构名不跨块,粘连无害)。
    """
    head_texts = [ir.title or "", *(b.text for b in ir.blocks[:HEAD_BLOCKS])]

    docnums: list[str] = []
    for t in head_texts:  # 版头逐块:文号(发文字号)在版头
        nt = _norm(t)
        for pat in _DOC_NUM_PATTERNS:
            docnums += pat.findall(nt)

    dates: list[date] = []
    for b in ir.blocks:  # 全文逐块:成文日期常在落款(文末)
        nt = _norm(b.text)
        for pat in (_DATE_CN, _DATE_ISO):
            for m in pat.finditer(nt):
                d = _safe_date(*m.groups())
                if d:
                    dates.append(d)

    head_joined = _norm(" ".join(head_texts))
    codes = [code for code, name in issuers if name and _norm(name) in head_joined]

    return L1Meta(
        doc_numbers=tuple(dict.fromkeys(docnums)),  # 去重保序
        dates=tuple(dict.fromkeys(dates)),
        issuer_codes=tuple(dict.fromkeys(codes)),
        title=ir.title,
    )


def resolve_issuer(value: str | None, issuers: list[tuple[str, str]]) -> str | None:
    """manifest issuer(可能填 code 或 name)解析为字典 code;解析不出返回 None(跳过该项校验)。"""
    v = _norm(value)
    if not v:
        return None
    for code, name in issuers:
        if _norm(code) == v or _norm(name) == v:
            return code
    return None


def cross_check(
    meta: L1Meta,
    *,
    doc_number: str | None,
    issue_date: date | None,
    issuer_code: str | None,
    title: str | None,
) -> list[Conflict]:
    """manifest 权威值 vs L1 候选:候选非空且 manifest 非空值不在候选中 → 冲突。"""
    out: list[Conflict] = []
    if doc_number and meta.doc_numbers:
        if _norm_dn(doc_number) not in {_norm_dn(x) for x in meta.doc_numbers}:
            out.append(Conflict("doc_number", doc_number, "/".join(meta.doc_numbers)))
    if issue_date and meta.dates and issue_date not in meta.dates:
        out.append(Conflict("issue_date", str(issue_date), "/".join(str(d) for d in meta.dates)))
    if issuer_code and meta.issuer_codes and issuer_code not in meta.issuer_codes:
        out.append(Conflict("issuer", issuer_code, "/".join(meta.issuer_codes)))
    if title and meta.title and _norm(title) != _norm(meta.title):
        out.append(Conflict("title", title, meta.title))
    return out
