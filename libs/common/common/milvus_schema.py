"""Milvus ``audit_corpus`` collection schema(§8.2)—— 契约:字段名/类型/partition key/向量维度。

只搬位置、值不变(字段全集对齐生产 §8.2)。建集合/索引/upsert/查询/冷备等 I/O **机制**仍在
``pipeline`` 的 ``index/milvus_io.py``(它从这里取 schema 定义)。
"""

from __future__ import annotations

from pymilvus import CollectionSchema, DataType, FieldSchema

#: BAAI/bge-m3 dense 维度(由模型决定,非 ⚠ 可调)
DENSE_DIM = 1024


def audit_corpus_schema() -> CollectionSchema:
    fields = [
        FieldSchema("chunk_id", DataType.VARCHAR, is_primary=True, max_length=24),
        FieldSchema("dense_vec", DataType.FLOAT_VECTOR, dim=DENSE_DIM),
        FieldSchema("sparse_vec", DataType.SPARSE_FLOAT_VECTOR),
        FieldSchema("doc_version_id", DataType.VARCHAR, max_length=26),
        # corpus_type 作 partition key(P-INT / P-EXT)
        FieldSchema("corpus_type", DataType.VARCHAR, max_length=16, is_partition_key=True),
        FieldSchema("status", DataType.VARCHAR, max_length=16),  # staging|effective|superseded
        FieldSchema("perm_tag", DataType.VARCHAR, max_length=32),  # 密级:写入,M1 不过滤
        FieldSchema("biz_domain", DataType.VARCHAR, max_length=64),
        FieldSchema("issuer_level", DataType.VARCHAR, max_length=32),
        FieldSchema("clause_path", DataType.VARCHAR, max_length=512),  # 四级引用:条款路径
        FieldSchema("page_start", DataType.INT64),  # 四级引用:页码
        FieldSchema("degraded", DataType.BOOL),
    ]
    return CollectionSchema(fields, description="审计语料库 audit_corpus(dense+sparse)")
