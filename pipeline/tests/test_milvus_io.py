"""milvus_io 集成测试(连 compose 的 Milvus;不可达时自动 skip)。"""

import pytest
from ulid import ULID

from pipeline.config import load_config
from pipeline.index.milvus_io import (
    DENSE_DIM,
    CorpusRow,
    MilvusIO,
    dense_from_bytes,
    dense_to_bytes,
    sparse_from_bytes,
    sparse_to_bytes,
)

DENSE = [float((i * 7) % 13) + 0.5 for i in range(1024)]
SPARSE = {"1": 0.9, "5": 0.3, "42": 0.6}


@pytest.fixture
def milvus():
    from pymilvus import utility

    mio = MilvusIO(load_config())
    try:
        mio.connect()
        utility.list_collections()  # 强制真实连接,不可达则 skip
    except Exception:
        pytest.skip("Milvus 不可达(demo up 未起)")
    mio.create_collection()  # 幂等
    yield mio
    mio.disconnect()


def test_schema_has_all_fields(milvus):
    fields = milvus.describe()
    expected = {
        "chunk_id",
        "dense_vec",
        "sparse_vec",
        "doc_version_id",
        "corpus_type",
        "status",
        "perm_tag",
        "biz_domain",
        "issuer_level",
        "clause_path",
        "page_start",
        "degraded",
    }
    assert expected <= set(fields)
    assert fields["dense_vec"] == "FLOAT_VECTOR"
    assert fields["sparse_vec"] == "SPARSE_FLOAT_VECTOR"
    assert fields["page_start"] == "INT64"


def test_partition_key_is_corpus_type(milvus):
    assert milvus.partition_key_field() == "corpus_type"


def test_dense_dim_matches_bge_m3():
    assert DENSE_DIM == 1024


# ── C5:upsert / flush / 混合查 / 冷备 ──────────────────────────
def test_cold_backup_roundtrip():
    # dense float32 往返(近似)+ sparse JSON 往返(精确);服务 rebuild 零重编码
    assert dense_from_bytes(dense_to_bytes([0.1, 0.2, 0.3])) == pytest.approx(
        [0.1, 0.2, 0.3], abs=1e-6
    )
    s = {"1": 0.5, "7": 0.25}
    assert sparse_from_bytes(sparse_to_bytes(s)) == s


@pytest.fixture
def dvid(milvus):
    d = str(ULID())
    yield d
    milvus.delete(d)
    milvus.flush()


def _row(dvid: str, suffix: str, *, status: str = "effective") -> CorpusRow:
    return CorpusRow(
        chunk_id=(dvid[:22] + suffix)[:24],
        dense=DENSE, sparse=SPARSE,
        doc_id=dvid, doc_version_id=dvid, corpus_type="P-INT", sub_type="内规",
        status=status,
        perm_tag=["内部"], biz_domain=["DISCLOSURE"], issuer_level=3,
        entity_type=[], chunk_type="clause",
        clause_path="第一章/第一条", page_start=1, effective_date=20240101,
        text="第一条 测试正文", degraded=False,
    )


def _dvids(res) -> list[str]:
    return [h["doc_version_id"] for h in res.hits]


def test_upsert_count(milvus, dvid):
    assert milvus.upsert([_row(dvid, "1"), _row(dvid, "2")]) == 2
    milvus.flush()
    assert milvus.count(dvid) == 2


def test_hybrid_search_returns_upserted(milvus, dvid):
    milvus.upsert([_row(dvid, "1")])
    milvus.flush()
    res = milvus.search(DENSE, SPARSE, topk=10)
    assert res.retrieval_mode == "hybrid"
    hit = next((h for h in res.hits if h["doc_version_id"] == dvid), None)
    assert hit is not None
    assert hit["clause_path"] == "第一章/第一条" and hit["page_start"] == 1  # 四级引用字段


def test_staging_invisible_even_with_include_superseded(milvus, dvid):
    # 硬契约:staging(INDEXED 前半成品)在任何情况下都不可见——include_superseded 也不放出。
    milvus.upsert([_row(dvid, "1", status="staging")])
    milvus.flush()
    assert dvid not in _dvids(milvus.search(DENSE, SPARSE, topk=20))  # 默认:staging 不可见
    visible = milvus.search(DENSE, SPARSE, topk=20, include_superseded=True)
    assert dvid not in _dvids(visible)  # include_superseded 仅放 superseded,staging 仍不可见


def test_superseded_visible_only_with_include_superseded(milvus, dvid):
    # superseded 旧版:默认不可见(仅 effective),include_superseded 才可见(V4 路径)。
    milvus.upsert([_row(dvid, "1", status="superseded")])
    milvus.flush()
    assert dvid not in _dvids(milvus.search(DENSE, SPARSE, topk=20))  # 默认仅 effective
    visible = milvus.search(DENSE, SPARSE, topk=20, include_superseded=True)
    assert dvid in _dvids(visible)  # 放出 superseded


def test_dense_only_fallback_on_empty_sparse(milvus, dvid):
    milvus.upsert([_row(dvid, "1")])
    milvus.flush()
    res = milvus.search(DENSE, {}, topk=10)  # 空 sparse → dense-only 兜底
    assert res.retrieval_mode == "dense_only"
    assert dvid in _dvids(res)


def test_corpus_filter(milvus, dvid):
    milvus.upsert([_row(dvid, "1")])  # corpus_type=P-INT
    milvus.flush()
    assert dvid in _dvids(milvus.search(DENSE, SPARSE, topk=20, corpus="P-INT"))
    assert dvid not in _dvids(milvus.search(DENSE, SPARSE, topk=20, corpus="P-EXT"))


def test_delete_removes_doc(milvus, dvid):
    milvus.upsert([_row(dvid, "1"), _row(dvid, "2")])
    milvus.flush()
    assert milvus.count(dvid) == 2
    milvus.delete(dvid)
    milvus.flush()
    assert milvus.count(dvid) == 0
