"""R1 混合检索:查询向量化 → milvus_io 混合检索(内规∥外规分区配额)→ 合并取 topk。

复用 ``pipeline.index``:``embedding_client``(查询 dense+sparse 一次产出)+ ``milvus_io``
(hybrid + RRFRanker + ``status==effective`` **前置过滤**,hybrid 失败 dense-only 兜底)。

§5.2 分区配额:内规(P-INT)/外规(P-EXT)**各打各的** ``partition_topk``,合并取 ``topk``——避免
外规 20x 体量淹没内规。§5.3 过滤位:status(milvus_io 内置 effective 前置)+ perm_tag(M1 预留不
过滤,与摄取侧一致)。entity_type/biz_domain 条件过滤本切片**暂缓**(``milvus_io.search`` 未暴露
附加 expr、hit 不带该字段);升级路径:pipeline 侧给 search 加附加 expr / output_fields(另议)。
"""

from __future__ import annotations

from dataclasses import dataclass

from pipeline.config import load_config
from pipeline.index.embedding_client import EmbeddingClient
from pipeline.index.milvus_io import MilvusIO
from query.config import QueryConfig, load_query_config

#: 检索分区(§5.2):内规 / 外规各打各的配额
_PARTITIONS = ("P-INT", "P-EXT")


@dataclass(frozen=True)
class Candidate:
    """检索候选(带 clause_id + 四级引用粗字段;精确锚点由 generate/anchors 回查 PG)。"""

    chunk_id: str
    score: float
    corpus_type: str | None
    doc_version_id: str | None
    clause_path: str | None
    page_start: int | None
    degraded: bool
    retrieval_mode: str  # hybrid | dense_only(命中所在分区的检索模式)


def _to_candidate(hit: dict, mode: str) -> Candidate:
    return Candidate(
        chunk_id=hit["chunk_id"],
        score=float(hit.get("score", 0.0)),
        corpus_type=hit.get("corpus_type"),
        doc_version_id=hit.get("doc_version_id"),
        clause_path=hit.get("clause_path"),
        page_start=hit.get("page_start"),
        degraded=bool(hit.get("degraded")),
        retrieval_mode=mode,
    )


def drop_degraded(candidates: list[Candidate]) -> list[Candidate]:
    """剔除 degraded 候选——契约:degraded 块仅全文检索、不参与条款级引用(CLAUDE.md)。"""
    return [c for c in candidates if not c.degraded]


class Retriever:
    """混合检索器:持有查询嵌入 + Milvus 客户端(连真栈)。"""

    def __init__(self, embed: EmbeddingClient, milvus: MilvusIO, qcfg: QueryConfig) -> None:
        self._embed = embed
        self._milvus = milvus
        self._qcfg = qcfg

    @classmethod
    def from_config(cls, qcfg: QueryConfig | None = None) -> Retriever:
        """连真栈:复用 pipeline 的 embedding/milvus(检索走本地真栈)。"""
        settings = load_config()
        milvus = MilvusIO(settings)
        milvus.connect()
        return cls(EmbeddingClient.from_config(settings), milvus, qcfg or load_query_config())

    def retrieve(self, query: str, *, include_superseded: bool = False) -> list[Candidate]:
        """分区配额检索 → 合并去重(同 chunk_id 保留更高分)→ 按分降序取 topk。"""
        emb = self._embed.embed([query])[0]
        merged: dict[str, Candidate] = {}
        for corpus in _PARTITIONS:
            res = self._milvus.search(
                emb.dense,
                emb.sparse,
                topk=self._qcfg.partition_topk,
                include_superseded=include_superseded,
                corpus=corpus,
            )
            for hit in res.hits:
                cand = _to_candidate(hit, res.retrieval_mode)
                prev = merged.get(cand.chunk_id)
                if prev is None or cand.score > prev.score:
                    merged[cand.chunk_id] = cand
        ranked = sorted(merged.values(), key=lambda c: c.score, reverse=True)
        return ranked[: self._qcfg.topk]
