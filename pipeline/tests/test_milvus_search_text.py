"""§5.5-T1(单元):milvus_io.search 加 ``with_text``(add-only)——输出 text + with_text=False 等价。

零真栈:monkeypatch ``MilvusIO._collection`` 返回 fake collection,断言 output_fields 与 hit.text。
守 **with_text=False 时 output_fields 与原 ``_OUTPUT_FIELDS`` byte 等价**(不回归 R1/R3/R4/R5/R6)。
"""

from __future__ import annotations

import pytest

from pipeline.index.milvus_io import _OUTPUT_FIELDS, MilvusIO

_ENTITY = {
    "doc_version_id": "DV1", "corpus_type": "P-INT", "status": "effective",
    "clause_path": "1/1", "page_start": 1, "degraded": False, "text": "条款正文摘要",
}


class _FakeHit:
    def __init__(self, cid):
        self.id = cid
        self.distance = 0.9
        self.entity = _ENTITY


class _FakeCollection:
    def __init__(self) -> None:
        self.fields = None

    def hybrid_search(self, reqs, ranker, *, limit, output_fields, consistency_level):
        self.fields = output_fields
        return [[_FakeHit("a1")]]

    def search(self, data, anns_field, param, *, limit, expr, output_fields, consistency_level):
        self.fields = output_fields
        return [[_FakeHit("a1")]]


@pytest.fixture
def mio(monkeypatch):
    m = MilvusIO.__new__(MilvusIO)
    fake = _FakeCollection()
    monkeypatch.setattr(m, "_collection", lambda: fake)
    return m, fake


_DENSE = [0.1, 0.2, 0.3]
_SPARSE = {1: 0.5}


def test_with_text_outputs_text(mio):
    m, fake = mio
    res = m.search(_DENSE, _SPARSE, topk=8, corpus="P-INT", with_text=True)
    assert "text" in fake.fields                       # output_fields 含 text
    assert res.hits[0]["text"] == "条款正文摘要"          # hit 透传 text


def test_without_text_equivalent(mio):
    # 守等价:with_text=False(默认)→ output_fields 与原 _OUTPUT_FIELDS byte 一致、hit 无 text 键
    m, fake = mio
    res = m.search(_DENSE, _SPARSE, topk=8, corpus="P-INT")
    assert fake.fields == _OUTPUT_FIELDS
    assert "text" not in res.hits[0]


def test_dense_fallback_with_text(mio):
    # sparse 空 → dense-only 兜底;with_text 同样带到 col.search(output_fields=)
    m, fake = mio
    res = m.search(_DENSE, {}, topk=8, corpus="P-EXT", with_text=True)
    assert res.retrieval_mode == "dense_only"
    assert "text" in fake.fields
    assert res.hits[0]["text"] == "条款正文摘要"
