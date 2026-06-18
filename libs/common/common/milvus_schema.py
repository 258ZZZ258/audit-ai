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
        FieldSchema("doc_id", DataType.VARCHAR, max_length=26),  # 逻辑文档 ID(跨版本操作)
        FieldSchema("doc_version_id", DataType.VARCHAR, max_length=26),
        # corpus_type 作 partition key(P-INT / P-EXT)
        FieldSchema("corpus_type", DataType.VARCHAR, max_length=16, is_partition_key=True),
        FieldSchema("sub_type", DataType.VARCHAR, max_length=32),  # 分层过滤(§8.2)
        # status: staging|effective|superseded|abolished|upcoming(默认强过滤位)
        FieldSchema("status", DataType.VARCHAR, max_length=16),
        # perm_tag/biz_domain/entity_type 为 ARRAY(§8.2);perm_tag 写入但 M1 不过滤
        FieldSchema(
            "perm_tag", DataType.ARRAY, element_type=DataType.VARCHAR, max_capacity=8, max_length=32
        ),
        FieldSchema(
            "biz_domain",
            DataType.ARRAY,
            element_type=DataType.VARCHAR,
            max_capacity=16,
            max_length=64,
        ),
        FieldSchema("issuer_level", DataType.INT8),  # 分层过滤(§8.2)
        FieldSchema(  # CP-007 适用实体类型(E2 富集产物,预留;摄取失败为空数组)
            "entity_type",
            DataType.ARRAY,
            element_type=DataType.VARCHAR,
            max_capacity=16,
            max_length=64,
        ),
        FieldSchema("chunk_type", DataType.VARCHAR, max_length=16),  # clause|table|qa|case_summary
        FieldSchema("clause_path", DataType.VARCHAR, max_length=512),  # 四级引用:条款路径
        FieldSchema("page_start", DataType.INT64),  # 四级引用:页码
        FieldSchema("effective_date", DataType.INT64),  # yyyymmdd 时间窗过滤
        FieldSchema("text", DataType.VARCHAR, max_length=2000),  # 检索-重排一跳;展示一律回查 PG
        FieldSchema("degraded", DataType.BOOL),
    ]
    return CollectionSchema(fields, description="审计语料库 audit_corpus(dense+sparse)")
