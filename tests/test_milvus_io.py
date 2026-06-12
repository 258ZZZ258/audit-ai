"""milvus_io 集成测试(连 compose 的 Milvus;不可达时自动 skip)。"""

import pytest

from pipeline.config import load_config
from pipeline.index.milvus_io import DENSE_DIM, MilvusIO


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
