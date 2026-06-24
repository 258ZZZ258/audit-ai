"""R5-T3(单元):answer_judgment 编排——judgmental+review_required / 桥接 / 空→拒答 / 无裸结论。

零栈:fake retriever + monkeypatch fetch_anchors/fetch_texts/resolve_cited_clauses。
"""

from __future__ import annotations

from types import SimpleNamespace

from query.config import load_query_config
from query.contract import Citation, RouteType
from query.judge import r5_judgment
from query.judge.r5_judgment import answer_judgment
from query.retrieve.hybrid import Candidate

_VERDICT_WORDS = ("违规", "违法", "合规", "合法", "可能违反", "疑似违规")


def _cand(cid, dvid, clause):
    return Candidate(cid, 1.0, "P-EXT", dvid, clause, 1, False, "hybrid")


class _Retr:
    def __init__(self, hybrid, cases=()):
        self._h, self._c = hybrid, cases

    def retrieve(self, q, *, include_superseded=False):
        return list(self._h)

    def retrieve_cases(self, q, *, include_superseded=False):
        return list(self._c)


def _cit(cid, title, clause):
    return Citation(clause_id=cid, doc_title=title, doc_no="令1", clause_path=clause,
                    page_start=1, status="effective")


def _patch(monkeypatch, anchors_map, texts_map, bridge_ids=()):
    monkeypatch.setattr(r5_judgment, "fetch_anchors",
                        lambda pg, ids: {i: anchors_map[i] for i in ids if i in anchors_map})
    monkeypatch.setattr(r5_judgment, "fetch_texts",
                        lambda pg, ids: {i: texts_map.get(i, "") for i in ids})
    monkeypatch.setattr(r5_judgment, "resolve_cited_clauses", lambda pg, dvids: list(bridge_ids))


def test_judgmental_with_review_required(monkeypatch):
    cands = [_cand("a1", "DV1", "第三条")]
    _patch(monkeypatch, {"a1": _cit("a1", "反洗钱管理办法", "第三条")}, {"a1": "客户身份识别"})
    res = answer_judgment("二维码介绍开户是否违规", _Retr(cands), pg=None, llm=None,
                          qcfg=load_query_config())
    assert res.route_type is RouteType.JUDGMENTAL
    assert res.review_required is True
    assert len(res.answer_blocks) == 2  # 三段式 ② 框定 + ③ 标识
    assert res.citations and res.citations[0].clause_id == "a1"
    for b in res.answer_blocks:  # 红线:无裸结论
        assert not any(w in b.content for w in _VERDICT_WORDS)


def test_bridge_consumed_when_present(monkeypatch):
    cands = [_cand("a1", "DV1", "第三条")]
    anchors = {"a1": _cit("a1", "内规X", "第三条"), "b1": _cit("b1", "外规Y", "第十条")}
    cases = [_cand("c1", "CASE1", None)]
    # 默认 cited_regulations 空 → 桥接 [] → 仅 hybrid
    _patch(monkeypatch, anchors, {"a1": "t", "b1": "t"}, bridge_ids=[])
    res = answer_judgment("q", _Retr(cands, cases), pg=None, llm=None, qcfg=load_query_config())
    assert [c.clause_id for c in res.citations] == ["a1"]
    # 手插桥接 → 外规条款入候选(桥接优先)
    _patch(monkeypatch, anchors, {"a1": "t", "b1": "t"}, bridge_ids=["b1"])
    res2 = answer_judgment("q", _Retr(cands, cases), pg=None, llm=None, qcfg=load_query_config())
    assert "b1" in [c.clause_id for c in res2.citations]


def test_empty_refuses(monkeypatch):
    _patch(monkeypatch, {}, {}, bridge_ids=[])
    res = answer_judgment("q", _Retr([], cases=[]), pg=None, llm=None, qcfg=load_query_config())
    assert res.route_type is RouteType.REFUSE
    assert res.exhausted_scope  # 可解释


def test_review_toggle_on_downgrades(monkeypatch):
    cands = [_cand("a1", "DV1", "第三条")]
    _patch(monkeypatch, {"a1": _cit("a1", "内规X", "第三条")}, {"a1": "t"})
    qcfg = load_query_config().model_copy(update={"judge_multimodel_review": True})
    fake_llm = SimpleNamespace(chat_json=lambda system, user: {"supported": False})
    res = answer_judgment("q", _Retr(cands), pg=None, llm=fake_llm, qcfg=qcfg)
    assert any("待人工核实" in b.content for b in res.answer_blocks)
