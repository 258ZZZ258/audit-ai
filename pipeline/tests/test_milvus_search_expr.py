"""R4-T3(单元):milvus_io.search 加 ``extra_expr``(add-only)——拼接正确 + extra_expr=None 等价。

零真栈:monkeypatch ``MilvusIO._collection`` 返回 fake collection,断言 ``SearchResult.expr`` 与
dense-only 兜底 ``col.search(expr=)`` 实参。守 **extra_expr=None 与原等价**(不回归 R1/R3/R6)。
"""

from __future__ import annotations

import pytest

from pipeline.index.milvus_io import MilvusIO


class _FakeCollection:
    """记录 dense-only 兜底收到的 expr;hybrid/dense 均返空命中(``_hits`` → [])。"""

    def __init__(self) -> None:
        self.dense_expr = None

    def hybrid_search(self, reqs, ranker, *, limit, output_fields, consistency_level):
        return [[]]

    def search(self, data, anns_field, param, *, limit, expr, output_fields, consistency_level):
        self.dense_expr = expr
        return [[]]


@pytest.fixture
def mio(monkeypatch):
    m = MilvusIO.__new__(MilvusIO)  # 不连真栈;search 只用 _collection()
    fake = _FakeCollection()
    monkeypatch.setattr(m, "_collection", lambda: fake)
    return m, fake


_DENSE = [0.1, 0.2, 0.3]
_SPARSE = {1: 0.5, 7: 0.3}


def test_extra_expr_none_equivalent(mio):
    # 守等价:extra_expr=None 时 expr 与原(status + corpus)byte 一致
    m, _ = mio
    res = m.search(_DENSE, _SPARSE, topk=8, corpus="P-INT")
    assert res.expr == 'status == "effective" and corpus_type == "P-INT"'
    assert res.retrieval_mode == "hybrid"


def test_extra_expr_appended_hybrid(mio):
    m, _ = mio
    res = m.search(_DENSE, _SPARSE, topk=8, corpus="P-INT", extra_expr='chunk_type == "clause"')
    assert res.expr == (
        'status == "effective" and corpus_type == "P-INT" and chunk_type == "clause"'
    )
    assert res.retrieval_mode == "hybrid"


def test_extra_expr_threaded_to_dense_fallback(mio):
    # sparse 空 → dense-only 兜底;extra_expr 须同样带到 col.search(expr=)
    m, fake = mio
    res = m.search(_DENSE, {}, topk=8, corpus="P-EXT", extra_expr='chunk_type == "clause"')
    assert res.retrieval_mode == "dense_only"
    assert fake.dense_expr == res.expr
    assert 'chunk_type == "clause"' in fake.dense_expr
    assert 'status == "effective"' in fake.dense_expr


def test_extra_expr_with_include_superseded(mio):
    m, _ = mio
    res = m.search(
        _DENSE, _SPARSE, topk=8, include_superseded=True, corpus="P-INT",
        extra_expr='chunk_type == "clause"',
    )
    assert res.expr == (
        'status in ["effective", "superseded"] and corpus_type == "P-INT" '
        'and chunk_type == "clause"'
    )


def test_no_corpus_no_extra_is_status_only(mio):
    # 守等价:无 corpus、无 extra_expr → 仅 status(原行为)
    m, _ = mio
    res = m.search(_DENSE, _SPARSE, topk=8)
    assert res.expr == 'status == "effective"'
