"""§5.5-T2(单元):重排接缝 + Candidate +text。零栈零模型(fake reranker model)。

NoneReranker passthrough(rerank=none byte 等价)· BGEReranker 按分降序 · make_reranker 分支 ·
Candidate +text(add-only,默认 None,向后兼容既有位置构造)。
"""

from __future__ import annotations

from types import SimpleNamespace

from query.config import QueryConfig
from query.rerank.reranker import BGEReranker, NoneReranker, make_reranker
from query.retrieve.hybrid import Candidate


def _c(cid, text):
    return SimpleNamespace(chunk_id=cid, text=text)


def test_none_passthrough():
    cands = [_c("a", ""), _c("b", ""), _c("c", "")]
    assert NoneReranker().rerank("q", cands) == cands  # 序不变 → rerank=none 等价


def test_bge_reorders_by_score():
    cands = [_c("a", "t1"), _c("b", "t2"), _c("c", "t3")]
    b = BGEReranker("fake")
    b._reranker = SimpleNamespace(compute_score=lambda pairs: [0.1, 0.9, 0.5])
    out = b.rerank("q", cands)
    assert [c.chunk_id for c in out] == ["b", "c", "a"]  # 按 cross-encoder 分降序


def test_bge_text_none_ok():
    b = BGEReranker("fake")
    b._reranker = SimpleNamespace(compute_score=lambda pairs: [0.5])
    assert b.rerank("q", [_c("a", None)])  # text=None → "" 不崩


def test_bge_empty():
    assert BGEReranker("fake").rerank("q", []) == []


def test_make_reranker_none():
    assert isinstance(make_reranker(QueryConfig(rerank_backend="none")), NoneReranker)


def test_make_reranker_bge_no_load():
    r = make_reranker(QueryConfig(rerank_backend="bge"))
    assert isinstance(r, BGEReranker)        # 懒载:构造不触发模型加载
    assert r._reranker is None


def test_candidate_text_backward_compat():
    # Candidate +text(add-only,默认 None):既有 8-arg 位置构造不破
    c = Candidate("a1", 1.0, "P-INT", "DV1", "1/1", 1, False, "hybrid")
    assert c.text is None
    c2 = Candidate("a1", 1.0, "P-INT", "DV1", "1/1", 1, False, "hybrid", "正文摘要")
    assert c2.text == "正文摘要"


# ── T3:Retriever 接线(主 retrieve rerank;with_text 由 rerank_backend 控)──────────
from query.retrieve.hybrid import Retriever  # noqa: E402


def _fake_milvus(captured):
    def _search(dense, sparse, *, topk, include_superseded=False, corpus=None,
                extra_expr=None, with_text=False):
        captured["with_text"] = with_text
        if corpus == "P-INT":
            return SimpleNamespace(
                hits=[{"chunk_id": "hi", "score": 0.9, "text": "t1"},
                      {"chunk_id": "lo", "score": 0.2, "text": "t2"}],
                retrieval_mode="hybrid",
            )
        return SimpleNamespace(hits=[], retrieval_mode="hybrid")
    return SimpleNamespace(search=_search)


_FAKE_EMBED = SimpleNamespace(embed=lambda texts: [SimpleNamespace(dense=[0.1], sparse={1: 0.5})])


def test_retriever_rerank_none_preserves_rrf_order():
    # rerank=none:with_text=False(零开销)+ 终态 = RRF 分降序(等价守护)
    captured: dict = {}
    r = Retriever(_FAKE_EMBED, _fake_milvus(captured), QueryConfig(rerank_backend="none"))
    out = r.retrieve("q")
    assert captured["with_text"] is False
    assert [c.chunk_id for c in out] == ["hi", "lo"]


def test_retriever_uses_injected_reranker():
    # rerank=bge:with_text=True + 注入 reranker(反转 RRF 序)→ 终态被重排
    captured: dict = {}
    rev = SimpleNamespace(rerank=lambda q, cands: list(reversed(cands)))
    r = Retriever(_FAKE_EMBED, _fake_milvus(captured), QueryConfig(rerank_backend="bge"),
                  reranker=rev)
    out = r.retrieve("q")
    assert captured["with_text"] is True
    assert [c.chunk_id for c in out] == ["lo", "hi"]  # RRF [hi,lo] 经反转重排 → [lo,hi]
