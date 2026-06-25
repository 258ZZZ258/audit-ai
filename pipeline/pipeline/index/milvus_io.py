"""Milvus IO:``audit_corpus`` collection 全 schema、建集合(A8)+ upsert/flush/混合查/冷备(C5)。

schema 全字段对齐生产 §8.2:dense+sparse 向量 + perm_tag/biz_domain/issuer_level 等标量 +
corpus_type 作 partition key;HNSW 参数从 config(⚠)。

C5:批量 upsert(``upsert_batch``/批,不自动 flush,写序由 s5 控)+ flush + 混合查(dense+sparse +
RRFRanker,默认 ``status=="effective"`` 过滤使 staging 不可见;hybrid 失败 → dense-only 兜底 +
``retrieval_mode`` 标记)+ count/delete(对账/reprocess)+ 冷备 serialize(dense float32 / sparse JSON →
PG bytea,服务 rebuild 零重编码)。
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np
from pymilvus import (
    AnnSearchRequest,
    Collection,
    CollectionSchema,
    RRFRanker,
    connections,
    utility,
)

from common.milvus_schema import DENSE_DIM, audit_corpus_schema
from pipeline.config import Settings

_ALIAS = "default"

#: 检索输出字段(四级引用 + 状态/降级标记)
_OUTPUT_FIELDS = [
    "chunk_id", "doc_version_id", "corpus_type", "status", "clause_path", "page_start", "degraded",
]


@dataclass
class CorpusRow:
    """一条待 upsert 的语料行(s5 从 chunk + 嵌入 + 文档元数据组装)。字段对齐生产 §8.2。"""

    chunk_id: str
    dense: list[float]
    sparse: dict[str, float]  # token_id(str)→权重;upsert 内转 {int: float}
    doc_id: str  # 逻辑文档 ID(跨版本)
    doc_version_id: str
    corpus_type: str
    sub_type: str
    status: str  # staging | effective | superseded | abolished | upcoming
    perm_tag: list[str]  # ARRAY(§8.2);demo 单值包成单元素 list
    biz_domain: list[str]  # ARRAY(§8.2)
    issuer_level: int  # INT8(§8.2);文本分层经 corpus_rows 映射
    entity_type: list[str]  # ARRAY(§8.2;CP-007,E2 富集,预留)
    chunk_type: str  # clause | table | …
    clause_path: str
    page_start: int
    effective_date: int  # yyyymmdd(0=未知)
    text: str  # 截断文本(检索-重排一跳;展示回查 PG)
    degraded: bool


@dataclass(frozen=True)
class SearchResult:
    hits: list[dict]  # 每条:chunk_id/score + 四级引用字段
    retrieval_mode: str  # hybrid | dense_only
    expr: str | None = None  # 实际过滤表达式(供 T2 冒烟断言 status 过滤位在)


# ── 冷备 serialize(dense float32 / sparse JSON → PG bytea;rebuild 零重编码反序列化)──
def dense_to_bytes(dense: list[float]) -> bytes:
    return np.asarray(dense, dtype=np.float32).tobytes()


def dense_from_bytes(b: bytes) -> list[float]:
    return np.frombuffer(b, dtype=np.float32).tolist()


def sparse_to_bytes(sparse: dict) -> bytes:
    return json.dumps({str(k): float(v) for k, v in sparse.items()}).encode("utf-8")


def sparse_from_bytes(b: bytes) -> dict[str, float]:
    return json.loads(b.decode("utf-8"))


def _sparse_for_milvus(sparse: dict) -> dict[int, float]:
    return {int(k): float(v) for k, v in sparse.items()}


def _to_milvus_dict(r: CorpusRow) -> dict:
    return {
        "chunk_id": r.chunk_id,
        "dense_vec": r.dense,
        "sparse_vec": _sparse_for_milvus(r.sparse),
        "doc_id": r.doc_id,
        "doc_version_id": r.doc_version_id,
        "corpus_type": r.corpus_type,
        "sub_type": r.sub_type,
        "status": r.status,
        "perm_tag": r.perm_tag,
        "biz_domain": r.biz_domain,
        "issuer_level": r.issuer_level,
        "entity_type": r.entity_type,
        "chunk_type": r.chunk_type,
        "clause_path": r.clause_path,
        "page_start": r.page_start,
        "effective_date": r.effective_date,
        "text": r.text,
        "degraded": r.degraded,
    }


def _hits(res, fields: list[str] = _OUTPUT_FIELDS) -> list[dict]:
    out = []
    for h in res[0]:  # 单查询:res[0]
        row = {"chunk_id": h.id, "score": float(h.distance)}
        for f in fields:
            if f != "chunk_id":
                row[f] = h.entity.get(f)
        out.append(row)
    return out


class MilvusIO:
    def __init__(self, settings: Settings) -> None:
        self.cfg = settings.milvus

    def connect(self) -> None:
        connections.connect(alias=_ALIAS, host=self.cfg.host, port=str(self.cfg.port))

    def disconnect(self) -> None:
        connections.disconnect(_ALIAS)

    def schema(self) -> CollectionSchema:
        """audit_corpus collection schema —— 契约定义在 common.milvus_schema(只搬位置,值不变)。"""
        return audit_corpus_schema()

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

    # ── C5:写入 / 对账 / 检索 ──────────────────────────────────
    def _collection(self) -> Collection:
        return Collection(self.cfg.collection)

    def upsert(self, rows: list[CorpusRow], *, batch_size: int | None = None) -> int:
        """按 ``upsert_batch`` 分批 upsert(**不 flush**,写序 PG→upsert→flush→INDEXED 由 s5 控)。"""
        if not rows:
            return 0
        bs = batch_size or self.cfg.upsert_batch
        col = self._collection()
        for i in range(0, len(rows), bs):
            col.upsert([_to_milvus_dict(r) for r in rows[i : i + bs]])
        return len(rows)

    def flush(self) -> None:
        self._collection().flush()

    def count(self, doc_version_id: str | None = None) -> int:
        """实体数:无参 = 全集合 num_entities;给 doc_version_id = 该文档块数(对账/幂等)。"""
        col = self._collection()
        if doc_version_id is None:
            return col.num_entities
        return len(
            col.query(
                f'doc_version_id == "{doc_version_id}"',
                output_fields=["chunk_id"],
                consistency_level="Strong",
            )
        )

    def delete(self, doc_version_id: str) -> None:
        """按 doc_version_id 删该文档全部块(reprocess / reconcile reload)。"""
        self._collection().delete(f'doc_version_id == "{doc_version_id}"')

    def probe_retrieval_mode(self) -> str:
        """探测当前可用检索模式(hybrid / dense_only),不依赖真实查询向量(供 report)。

        用合成向量发一次 topk=1 查询:hybrid_search 成功 → "hybrid",受阻退化 → "dense_only"
        (复用 search 的兜底逻辑)。命中与否不影响判定。
        """
        probe_dense = [0.0] * DENSE_DIM
        probe_dense[0] = 1.0  # 非零向量(COSINE 需 norm≠0)
        return self.search(probe_dense, {"0": 1.0}, topk=1).retrieval_mode

    def search(
        self,
        dense: list[float],
        sparse: dict[str, float],
        *,
        topk: int,
        include_superseded: bool = False,
        corpus: str | None = None,
        extra_expr: str | None = None,
        with_text: bool = False,
    ) -> SearchResult:
        """混合查(dense+sparse + RRFRanker);hybrid 失败或 sparse 空 → dense-only 兜底 + 标记。

        默认按 status==effective 过滤;include_superseded 额外放出 superseded 旧版(V4 路径,
        status in [effective, superseded])。**staging(INDEXED 前半成品)在任何情况下都不可见**
        ——这是硬契约(写序 PG→upsert→flush→INDEXED,翻 effective 前不暴露),故 include_superseded
        只放宽到 superseded、绝不去掉 status 过滤。corpus 加 corpus_type 过滤。
        ``extra_expr`` 追加调用方标量过滤(R4 枚举:chunk_type/biz_domain/entity_type;**add-only**,
        为 None 时 expr 与原行为等价,不改 status/corpus 语义)。
        ``with_text`` 额外输出 Milvus 截断 ``text``(§5.5 检索-重排一跳;**add-only**,为 False 时
        output_fields 与原 ``_OUTPUT_FIELDS`` 等价,不回归)。
        hit 带四级引用字段(clause_path/doc_version_id/page_start)。
        """
        col = self._collection()
        # staging 永不可见(硬契约);include_superseded 仅把可见集放宽到含 superseded
        status_clause = (
            'status in ["effective", "superseded"]'
            if include_superseded
            else 'status == "effective"'
        )
        clauses = [status_clause]
        if corpus:
            clauses.append(f'corpus_type == "{corpus}"')
        if extra_expr:
            clauses.append(extra_expr)  # 调用方标量过滤(白名单字段 + 转义值,见 query.listing)
        expr = " and ".join(clauses)
        out_fields = [*_OUTPUT_FIELDS, "text"] if with_text else _OUTPUT_FIELDS

        try:
            if not sparse:
                raise ValueError("空 sparse,转 dense-only")
            reqs = [
                AnnSearchRequest(
                    [dense], "dense_vec", {"metric_type": "COSINE", "params": {}},
                    limit=topk, expr=expr,
                ),
                AnnSearchRequest(
                    [_sparse_for_milvus(sparse)], "sparse_vec", {"metric_type": "IP", "params": {}},
                    limit=topk, expr=expr,
                ),
            ]
            res = col.hybrid_search(
                reqs, RRFRanker(), limit=topk,
                output_fields=out_fields, consistency_level="Strong",
            )
            return SearchResult(_hits(res, out_fields), "hybrid", expr)
        except Exception:  # hybrid 受阻(R2 兜底,不静默)→ dense-only
            res = col.search(
                [dense], "dense_vec", {"metric_type": "COSINE", "params": {}},
                limit=topk, expr=expr, output_fields=out_fields, consistency_level="Strong",
            )
            return SearchResult(_hits(res, out_fields), "dense_only", expr)
