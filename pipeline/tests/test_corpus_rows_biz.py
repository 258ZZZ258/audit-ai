"""T2.3b 下游取值:Milvus ``biz_domain`` ARRAY 从 ``doc_versions.biz_domains`` 取(回落单值)。

纯逻辑(免栈):注入 fake db,验 ``corpus_rows.build_rows`` 的业务域取值优先级。
"""

from __future__ import annotations

from common.pg_models import Chunk, Document, DocVersion
from pipeline.index.corpus_rows import build_rows


class _FakeDb:
    def __init__(self, dv, doc):
        self._dv, self._doc = dv, doc

    def get(self, model, pk):
        return self._dv if model is DocVersion else self._doc

    def get_issuers(self):
        return []


def _row_for(biz_domains, biz_domain):
    dv = DocVersion(
        doc_version_id="dv1", logical_id="l1", source_format="docx", source_hash="h",
        raw_object_key="k", biz_domains=biz_domains, biz_domain=biz_domain,
    )
    doc = Document(logical_id="l1", corpus_type="P-INT")
    chunk = Chunk(
        chunk_id="c1", doc_version_id="dv1", text="x", clause_path="1", seq=0,
        chunk_status="staging",
    )
    rows = build_rows(_FakeDb(dv, doc), "dv1", [chunk], [([0.1], {"1": 0.2})], "staging")
    return rows[0]


def test_build_rows_biz_from_biz_domains_multi():
    row = _row_for(["经纪业务", "投行业务"], "旧单值")
    assert row.biz_domain == ["经纪业务", "投行业务"]  # L2 多值优先(不取旧单值)


def test_build_rows_biz_fallback_to_single():
    row = _row_for(None, "经纪业务")
    assert row.biz_domain == ["经纪业务"]  # biz_domains 空 → 回落 manifest 原单值(向后兼容)


def test_build_rows_biz_empty_when_both_absent():
    assert _row_for(None, None).biz_domain == []
