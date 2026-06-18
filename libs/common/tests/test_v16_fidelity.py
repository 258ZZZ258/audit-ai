"""契约层 v1.6 保真补齐的 schema pin(CP-007 + 版本生命周期 + §8.2/§8.3 字段)。

只钉"字段存在 + 关键类型",不钉值;行为正确性由各阶段单测把关。
"""

from __future__ import annotations

from pymilvus import DataType

from common.ir import Block, BlockType
from common.manifest import REQUIRED_COLUMNS
from common.milvus_schema import audit_corpus_schema
from common.pg_models import Chunk, ClauseTag, DocVersion


def _milvus_fields() -> dict:
    return {f.name: f for f in audit_corpus_schema().fields}


# ── Milvus audit_corpus(§8.2)────────────────────────────────────────────────
def test_milvus_new_fields_present() -> None:
    f = _milvus_fields()
    for name in ["doc_id", "sub_type", "effective_date", "chunk_type", "text", "entity_type"]:
        assert name in f, f"Milvus 缺字段 {name}"


def test_milvus_array_and_int8_types() -> None:
    f = _milvus_fields()
    assert f["perm_tag"].dtype == DataType.ARRAY
    assert f["perm_tag"].element_type == DataType.VARCHAR
    assert f["biz_domain"].dtype == DataType.ARRAY
    assert f["entity_type"].dtype == DataType.ARRAY
    assert f["issuer_level"].dtype == DataType.INT8
    assert f["effective_date"].dtype == DataType.INT64
    assert f["text"].dtype == DataType.VARCHAR


def test_milvus_pk_and_partition_key_unchanged() -> None:
    f = _milvus_fields()
    assert f["chunk_id"].is_primary
    assert f["corpus_type"].is_partition_key


# ── PG 模型(§8.3/§10,CP-007)────────────────────────────────────────────────
def test_chunks_new_columns() -> None:
    cols = Chunk.__table__.columns.keys()
    for c in ["chunk_type", "parent_chunk_id", "internal_refs", "embed_status", "entity_type"]:
        assert c in cols, f"chunks 缺列 {c}"


def test_clause_tags_typed_columns_added_kv_kept() -> None:
    cols = ClauseTag.__table__.columns.keys()
    for c in [
        "deontic_type",
        "norm_duration_days",
        "surface_duration",
        "is_business_day",
        "norm_status",
        "entity_type",
    ]:
        assert c in cols, f"clause_tags 缺类型列 {c}"
    # R2(a):k-v 列保留(add-only,不破现有 E1)
    for c in ["tag_type", "tag_value", "evidence"]:
        assert c in cols


def test_doc_versions_new_columns() -> None:
    cols = DocVersion.__table__.columns.keys()
    assert "sub_type" in cols
    assert "effective_date" in cols


# ── manifest(§3.1)───────────────────────────────────────────────────────────
def test_manifest_required_adds_subtype_and_effective_date() -> None:
    assert "sub_type" in REQUIRED_COLUMNS
    assert "effective_date" in REQUIRED_COLUMNS
    assert len(REQUIRED_COLUMNS) == 11


# ── IR Block.level(§4.2)──────────────────────────────────────────────────────
def test_block_accepts_level_and_optional() -> None:
    b = Block(index=0, type=BlockType.HEADING, level=2, text="第一章 总则")
    assert b.level == 2
    assert Block(index=1, type=BlockType.PARAGRAPH, text="x").level is None
