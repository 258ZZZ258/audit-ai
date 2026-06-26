"""§5.4:查询层 sparse 精确增强(发文字号提权 + 词典扩展)。纯函数,零栈零模型(embed 注入)。

- ``detect_doc_numbers``:``to_halfwidth`` 归一后 regex 检发文字号 + 《全名》。
- ``load_scenario_terms``:读 CSV(``oral_term,legal_terms``,``|`` 分隔)→ dict;缺/空/坏行 → {}。
- ``augment_sparse``:检出 span / 法言词 → ``embed`` 注入,选择性 token 加权并入 query sparse;
  无命中 → 返回 ``base_sparse`` 原样(byte 等价)。只动 sparse(RRF 基于秩,uniform 缩放无效)。
"""

from __future__ import annotations

import csv
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from pipeline.chunking.normalize import to_halfwidth

# 发文字号 = 机关代字 + 〔年〕(全角（）→ () via to_halfwidth,CJK〔〕不变)+ 第?序号 + 号。
# 机关代字用**字符白名单**(机关简称 + 文种字)界定边界:口语/语法字(看/了/这/依…)不在集合内,
# 贪婪也不会卷入 span(稳健于停词黑名单,QUERY-SPARSE-DOCNUM-SPAN;罕见代字需字典/分词,§15-V0)。
_BRA_OPEN = "〔(\\[【"
_BRA_CLOSE = "〕)\\]】"
_DAIZI = (
    "银保监证期基金信财会计审税国中央行人民政公安司法农水文卫"
    "环资源应急交通住建发改委办部局厅署院教科工商务海关质检统综纪"
)
_DOCNUM_RE = re.compile(
    rf"[{_DAIZI}]{{0,8}}[{_BRA_OPEN}][12]\d{{3}}[{_BRA_CLOSE}]\s*第?\s*\d{{1,4}}\s*[号號]"
)
# 制度全名:《…》(2–40 字,不嵌套)
_TITLE_RE = re.compile(r"《[^《》]{2,40}》")


def detect_doc_numbers(query: str) -> list[str]:
    """检发文字号 + 制度全名 span(``to_halfwidth`` 归一;机关代字字符白名单界定边界);去重保序。"""
    norm = to_halfwidth(query)
    out: list[str] = []
    for m in _DOCNUM_RE.finditer(norm):
        s = m.group(0).strip()
        if s and s not in out:
            out.append(s)
    for m in _TITLE_RE.finditer(norm):
        s = m.group(0).strip()
        if s and s not in out:
            out.append(s)
    return out


def load_scenario_terms(path: str | Path) -> dict[str, list[str]]:
    """读 ``dict_scenario_terms.csv``(``oral_term,legal_terms`` `|` 分隔)→ dict。

    consumed-when-present:文件缺 / 空 / 坏行 → ``{}`` / 跳过该行(不抛,不阻塞检索)。
    """
    p = Path(path)
    if not p.exists():
        return {}
    out: dict[str, list[str]] = {}
    with p.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            oral = (row.get("oral_term") or "").strip()
            legal = [t.strip() for t in (row.get("legal_terms") or "").split("|") if t.strip()]
            if oral and legal:
                out[oral] = legal
    return out


def _matched_legal_terms(query: str, terms: Mapping[str, Sequence[str]]) -> list[str]:
    """口语词子串命中 → 映射法言词(扁平去重保序)。"""
    out: list[str] = []
    for oral, legal in terms.items():
        if oral and oral in query:
            for t in legal:
                if t not in out:
                    out.append(t)
    return out


def augment_sparse(
    query: str,
    base_sparse: dict,
    *,
    embed,
    scenario_terms: Mapping[str, Sequence[str]] | None = None,
    docnum_factor: float = 2.0,
    expand_factor: float = 1.0,
    docnum_on: bool = False,
    expand_on: bool = False,
) -> dict:
    """对 query sparse 做精确增强:发文字号/全名提权 + 法言词扩展。

    无命中(双关关 / 无发文字号 + 无 dict 命中)→ 返回 ``base_sparse`` 同一对象(byte 等价根)。
    命中 → 复制 base + ``embed(spans)`` 的 token 按 factor 加权并入(只返 sparse)。
    """
    spans: list[tuple[str, float]] = []
    if docnum_on:
        spans += [(s, docnum_factor) for s in detect_doc_numbers(query)]
    if expand_on and scenario_terms:
        spans += [(t, expand_factor) for t in _matched_legal_terms(query, scenario_terms)]
    if not spans:
        return base_sparse  # 无命中 → 原样(同一性 → byte 等价)
    out = dict(base_sparse)
    for (_, factor), vec in zip(spans, embed.embed([s for s, _ in spans]), strict=True):
        for tok, w in vec.sparse.items():
            out[tok] = out.get(tok, 0.0) + factor * w
    return out
