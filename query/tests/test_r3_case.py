"""T3(单元):R3 编排纯部分——去重一案一卡 / 空命中明示 / get_case None 跳过 / 附挂去重+零命中不挂。

零栈零模型:fake retriever(返回 Candidate)+ fake pg(get_case/get/session)。
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from query.case.r3_case import answer_case, attach_cases
from query.contract import BlockType, Citation, QueryResult, RouteType
from query.retrieve.hybrid import Candidate

_QCFG = SimpleNamespace(topk=8, attach_topk=3)


def _cand(chunk_id, dvid, score=1.0, degraded=False):
    return Candidate(
        chunk_id=chunk_id, score=score, corpus_type="P-CASE", doc_version_id=dvid,
        clause_path=None, page_start=None, degraded=degraded, retrieval_mode="hybrid",
    )


def _case_row(dvid, refs=None):
    return SimpleNamespace(
        doc_version_id=dvid, penalty_org="XX证监局", penalty_date=date(2024, 3, 11),
        respondent="XX公司", penalty_type="罚款", amount_wan=50.0,
        violation_category=None, cited_regulations=refs or [],
    )


def _dv(dvid, title="XX处罚决定书"):
    return SimpleNamespace(title=title, doc_number="〔2024〕1号",
                           issue_date=date(2024, 3, 11), version_status="effective")


class _FakeRetriever:
    def __init__(self, cands):
        self._cands = cands

    def retrieve_cases(self, query, *, include_superseded=False):
        return list(self._cands)


class _FakeSession:
    def __init__(self, cases):
        self._cases = cases

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def scalars(self, _stmt):
        return list(self._cases)


class _FakePg:
    def __init__(self, cases, dvs=None):
        self._cases = {c.doc_version_id: c for c in cases}
        self._dvs = dvs or {}

    def get_case(self, dvid):
        return self._cases.get(dvid)

    def get(self, _model, pk):
        return self._dvs.get(pk)

    def session(self):
        return _FakeSession(list(self._cases.values()))


def _card_count(res):
    return sum(1 for b in res.answer_blocks if b.type is BlockType.CASE_CARD)


# ── R3 route:answer_case ──────────────────────────────────────────────
def test_dedup_one_card_per_case():
    # 同案两 chunk(summary + section)命中 → 一案一卡
    retr = _FakeRetriever([_cand("c-sum", "DV1", 0.9), _cand("c-sec", "DV1", 0.8)])
    pg = _FakePg([_case_row("DV1")], {"DV1": _dv("DV1")})
    res = answer_case("有没有类似案例", retr, pg, _QCFG)
    assert res.route_type is RouteType.CASE
    assert _card_count(res) == 1


def test_no_hits_explicit():
    res = answer_case("有没有类似案例", _FakeRetriever([]), _FakePg([]), _QCFG)
    assert res.route_type is RouteType.CASE
    assert _card_count(res) == 0
    assert "未检索到" in res.answer_blocks[0].content   # 明示、不报错、不臆造


def test_get_case_none_skipped():
    # 命中 dvid 但 cases 无该行 → 跳过该卡(不臆造);全跳 → 兜底明示
    retr = _FakeRetriever([_cand("c1", "DV-missing")])
    res = answer_case("有没有类似案例", retr, _FakePg([]), _QCFG)
    assert _card_count(res) == 0 and "未检索到" in res.answer_blocks[0].content


def test_degraded_dropped():
    retr = _FakeRetriever([_cand("c1", "DV1", degraded=True)])
    pg = _FakePg([_case_row("DV1")], {"DV1": _dv("DV1")})
    res = answer_case("有没有类似案例", retr, pg, _QCFG)
    assert _card_count(res) == 0   # degraded 不入卡片


# ── 附挂:attach_cases ────────────────────────────────────────────────
def _evidence_result():
    from query.contract import AnswerBlock
    return QueryResult(
        route_type=RouteType.EVIDENCE,
        answer_blocks=[AnswerBlock(BlockType.TEXT, "依据答复")],
        citations=[Citation(clause_id="x", doc_no="〔2024〕1号", clause_path="第三条")],
        confidence=0.7,
    )


def test_attach_zero_hit_unchanged():
    # 语义零命中 + 精确零命中(citations=[]) → 原样返回,不挂
    res0 = _evidence_result()
    res = attach_cases(res0, "q", [], _FakeRetriever([]), _FakePg([]), _QCFG)
    assert _card_count(res) == 0
    assert [b.content for b in res.answer_blocks] == ["依据答复"]


def test_attach_appends_semantic_cards_keep_existing():
    res0 = _evidence_result()
    retr = _FakeRetriever([_cand("c1", "DV1")])
    pg = _FakePg([_case_row("DV1")], {"DV1": _dv("DV1")})
    res = attach_cases(res0, "q", [], retr, pg, _QCFG)
    assert _card_count(res) == 1
    # 既有 evidence 文本块 + citations 不变(追加块)
    assert res.answer_blocks[0].content == "依据答复"
    assert [c.clause_id for c in res.citations] == ["x"]


def test_attach_precise_reverse_lookup_priority():
    # 精确反查命中 DV2(citation 外规条款 → cited_regulations)排在语义 DV1 前
    res0 = _evidence_result()
    retr = _FakeRetriever([_cand("c1", "DV1")])
    pg = _FakePg(
        [_case_row("DV1"),
         _case_row("DV2", refs=[{"doc_no": "〔2024〕1号", "clause_path": "第三条"}])],
        {"DV1": _dv("DV1"), "DV2": _dv("DV2", title="精确反查命中案")},
    )
    res = attach_cases(res0, "q", res0.citations, retr, pg, _QCFG)
    import json
    cards = [json.loads(b.content) for b in res.answer_blocks if b.type is BlockType.CASE_CARD]
    assert cards[0]["doc_version_id"] == "DV2"   # 精确反查优先
    assert {c["doc_version_id"] for c in cards} == {"DV1", "DV2"}
