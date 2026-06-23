"""T2(单元):案例桥接精确反查——norm_ref 归一 / 索引 / 命中 / **空降级**(consumed-when-present)。

纯逻辑零栈:``index_from_cases`` 接 cases 行可迭代;``cases_for_clauses`` 用 fake pg(返回 cases 行)。
"""

from __future__ import annotations

from types import SimpleNamespace

from query.case.bridge import (
    cases_for_clauses,
    citation_key,
    index_from_cases,
    norm_ref,
)


def _case(dvid, refs):
    return SimpleNamespace(doc_version_id=dvid, cited_regulations=refs)


class _FakeSession:
    def __init__(self, cases):
        self._cases = cases

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def scalars(self, _stmt):  # 忽略 stmt,返回全部 cases(过滤由 index_from_cases 兜)
        return list(self._cases)


class _FakePg:
    def __init__(self, cases):
        self._cases = cases

    def session(self):
        return _FakeSession(self._cases)


def test_norm_ref_equivalence_halfwidth_brackets_ws():
    a = norm_ref("〔2024〕1号", "第三条")
    b = norm_ref("[2024]1号", "第三条")        # 括号变体归一
    c = norm_ref(" 〔2024〕1号 ", "第三条")      # 去空白
    assert a == b == c
    assert a != norm_ref("〔2024〕2号", "第三条")  # 不同文号不等
    assert a != norm_ref("〔2024〕1号", "第四条")  # 不同条款不等


def test_index_from_cases_maps_ref_to_dvids():
    cases = [
        _case("DV1", [{"doc_no": "〔2024〕1号", "clause_path": "第三条"}]),
        _case("DV2", [{"doc_no": "[2024]1号", "clause_path": "第三条"}]),  # 同条款异写
    ]
    idx = index_from_cases(cases)
    assert set(idx[norm_ref("〔2024〕1号", "第三条")]) == {"DV1", "DV2"}


def test_index_skips_empty_and_unparseable():
    cases = [
        _case("DV1", []),                 # 空 → 无条目
        _case("DV2", None),               # None → 无条目
        _case("DV3", ["纯字符串无结构"]),  # 不可解析(非 dict)→ 跳过
        _case("DV4", [{"foo": "bar"}]),   # 无 doc_no/clause_path → 跳过
    ]
    assert index_from_cases(cases) == {}


def test_cases_for_clauses_match():
    pg = _FakePg([_case("DV1", [{"doc_no": "〔2024〕1号", "clause_path": "第三条"}])])
    key = norm_ref("〔2024〕1号", "第三条")
    assert cases_for_clauses(pg, [key]) == ["DV1"]
    assert cases_for_clauses(pg, []) == []             # 无键 → []
    assert cases_for_clauses(pg, ["不存在的键"]) == []  # 未命中 → []


def test_cases_for_clauses_empty_cited_degrades():
    # 默认路径:cited_regulations 全空 → 索引空 → 精确反查 []( 降级语义-only)
    pg = _FakePg([_case("DV1", []), _case("DV2", None)])
    key = norm_ref("〔2024〕1号", "第三条")
    assert cases_for_clauses(pg, [key]) == []


def test_citation_key_from_citation():
    cit = SimpleNamespace(doc_no="〔2024〕1号", clause_path="第三条")
    assert citation_key(cit) == norm_ref("〔2024〕1号", "第三条")
