"""Milvus IO:``audit_corpus`` collection 全 schema 与建集合(A8)。

M1 仅建集合;upsert/flush/混合查/冷备在 C5 接入。
schema 全字段对齐生产 §8.2:dense+sparse 向量 + perm_tag/biz_domain/issuer_level 等标量 +
corpus_type 作 partition key;HNSW 参数从 config(⚠)。
"""

from __future__ import annotations

from pymilvus import (
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    connections,
    utility,
)

from pipeline.config import Settings

#: BAAI/bge-m3 dense 维度(由模型决定,非 ⚠ 可调)
DENSE_DIM = 1024

_ALIAS = "default"


class MilvusIO:
    def __init__(self, settings: Settings) -> None:
        self.cfg = settings.milvus

    def connect(self) -> None:
        connections.connect(alias=_ALIAS, host=self.cfg.host, port=str(self.cfg.port))

    def disconnect(self) -> None:
        connections.disconnect(_ALIAS)

    def schema(self) -> CollectionSchema:
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

    def create_collection(self, *, drop_existing: bool = False) -> Collection:
        """建 audit_corpus + 索引(dense=HNSW/COSINE,sparse=SPARSE_INVERTED_INDEX/IP)。

        已存在则复用(drop_existing=True 时先删,服务 rebuild)。需先 connect()。
        """
        name = self.cfg.collection
        if utility.has_collection(name):
            if not drop_existing:
                return Collection(name)
            utility.drop_collection(name)

        col = Collection(name, schema=self.schema())
        col.create_index(
            "dense_vec",
            {
                "index_type": "HNSW",
                "metric_type": "COSINE",
                "params": {"M": self.cfg.hnsw_m, "efConstruction": self.cfg.hnsw_ef_construction},
            },
        )
        col.create_index(
            "sparse_vec",
            {"index_type": "SPARSE_INVERTED_INDEX", "metric_type": "IP"},
        )
        col.load()
        return col

    def describe(self) -> dict[str, str]:
        """字段名 → 类型(供验证)。需先 connect() 且集合已建。"""
        col = Collection(self.cfg.collection)
        return {f.name: f.dtype.name for f in col.schema.fields}

    def partition_key_field(self) -> str | None:
        col = Collection(self.cfg.collection)
        for f in col.schema.fields:
            if getattr(f, "is_partition_key", False):
                return f.name
        return None
