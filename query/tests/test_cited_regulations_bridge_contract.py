"""producer↔consumer 契约回归:case_l2(T2.1)产出的 ``cited_regulations`` 形态被 query 反查识别。

Codex CASE-L2-CITED-REGULATIONS-SHAPE:producer 必须发 ``doc_no``(非 DB 列名 ``doc_number``),
否则 ``query/case/bridge.py`` 与 ``query/judge/r5_judgment.py`` 的反查键缺文号(形如 ``|2/15``)、
案例→外规反查失效。纯逻辑(无栈、无 LLM):注入 fake client/lookup 取 case_l2 真实产出喂消费者。
"""

from __future__ import annotations

import types

from pipeline.meta import case_l2
from pipeline.meta.case_ref_align import RegDoc
from query.case.bridge import _entry_key, index_from_cases
from query.judge.r5_judgment import _entry_doc_clause


class _FakeClient:
    def __init__(self, fn):
        self._fn = fn

    def chat_json(self, system, user):
        return self._fn(system, user)


class _FakeLookup:
    def __init__(self, by_doc):
        self._by_doc = by_doc

    def find(self, doc_number, title):
        return self._by_doc.get(doc_number)


def _producer_output():
    """跑 ``case_l2.l2_fields``(fake LLM + fake lookup)取真实 cited_regulations 产出。"""
    regdoc = RegDoc(
        doc_version_id="DVX", doc_number="〔2020〕5号", clause_norms=frozenset({"2/15"})
    )

    def chat(system, user):
        if "引用外规" in system:
            return {"cited": [{"title": "条例", "doc_number": "〔2020〕5号", "clause": "第十五条"}]}
        return {"violation_category": None}

    return case_l2.l2_fields(
        "案情",
        client=_FakeClient(chat),
        lookup=_FakeLookup({"〔2020〕5号": regdoc}),
        allowed_violations={},
    )


def test_producer_shape_consumed_by_bridge_and_r5():
    out = _producer_output()
    entry = out["cited_regulations"][0]
    # producer 发 doc_no(非 doc_number)+ clause_path_norm
    assert entry["doc_no"] == "〔2020〕5号"
    assert entry["clause_path_norm"] == "2/15"

    # bridge._entry_key:键含归一文号(非缺文号的 "|2/15" 形态)
    key = _entry_key(entry)
    assert key is not None and not key.startswith("|")

    # r5_judgment._entry_doc_clause:doc_no AND clause 都解析得出(否则 resolve_cited_clauses 跳过)
    assert _entry_doc_clause(entry) is not None

    # index_from_cases:案例被反查索引(非空 + 命中该 case 的 dvid)
    case = types.SimpleNamespace(doc_version_id="CASE1", cited_regulations=out["cited_regulations"])
    index = index_from_cases([case])
    assert index
    assert "CASE1" in next(iter(index.values()))
