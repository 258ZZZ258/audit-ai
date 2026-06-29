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
from query.retrieve.decompose import decompose_subqueries
from query.retrieve.hyde import hyde_dense_text
from query.retrieve.sparse_boost import augment_sparse, load_scenario_terms

#: 检索分区(§5.2):内规 / 外规各打各的配额
_PARTITIONS = ("P-INT", "P-EXT")


def _build_hyde_llm(qcfg: QueryConfig):
    """§3.1 N1:HyDE 归并客户端**仅 hyde 开 + gateway 时建**(镜像 §9.2/N0);否则 None → 原问 dense。

    默认 stub → None → HyDE no-op(零网络、byte 等价)。「默认开」仅在配 gateway 时活。
    """
    if qcfg.hyde and qcfg.llm_backend == "gateway":
        from query.llm import make_llm_client  # 懒导入,避 import 期拉 pipeline.llm_client

        return make_llm_client(qcfg, model=qcfg.hyde_model or qcfg.llm_model)
    return None


def _build_decompose_llm(qcfg: QueryConfig):
    """§3.3 N3:分解客户端**仅 decompose 开 + gateway 时建**(镜像 N1);否则 None → 单查询直通。

    默认 stub → None → `_subqueries_for` 返 [query](零网络、byte 等价)。「默认开」仅 gateway 时活。
    """
    if qcfg.decompose and qcfg.llm_backend == "gateway":
        from query.llm import make_llm_client  # 懒导入

        return make_llm_client(qcfg, model=qcfg.decompose_model or qcfg.llm_model)
    return None


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
    text: str | None = None  # §5.5 Milvus 截断 text(仅 with_text 检索-重排一跳填;默认 None)


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
        text=hit.get("text"),  # with_text=False 时 None(rerank=none 路径无开销)
    )


def drop_degraded(candidates: list[Candidate]) -> list[Candidate]:
    """剔除 degraded 候选——契约:degraded 块仅全文检索、不参与条款级引用(CLAUDE.md)。"""
    return [c for c in candidates if not c.degraded]


class Retriever:
    """混合检索器:持有查询嵌入 + Milvus 客户端(连真栈)。"""

    def __init__(
        self, embed: EmbeddingClient, milvus: MilvusIO, qcfg: QueryConfig, reranker=None,
        hyde_llm=None, decompose_llm=None,
    ) -> None:
        from query.rerank.reranker import make_reranker  # 局部导入,避 import 期环

        self._embed = embed
        self._milvus = milvus
        self._qcfg = qcfg
        # rerank_backend=none → NoneReranker(passthrough,byte 等价);bge → 本地 reranker
        self._reranker = reranker if reranker is not None else make_reranker(qcfg)
        # §5.4 词典扩展种子(consumed-when-present;scenario_expand 关 → {} 免 IO)
        self._scenario_terms = (
            load_scenario_terms(qcfg.scenario_terms_path) if qcfg.scenario_expand else {}
        )
        # §3.1 N1 HyDE dense 改写客户端(仅 hyde 开+gateway;否则 None → 原问 dense,byte 等价)
        self._hyde_llm = hyde_llm
        # §3.3 N3 问题分解客户端(仅 decompose 开+gateway;否则 None → 单查询 [query],byte 等价)
        self._decompose_llm = decompose_llm

    @classmethod
    def from_config(cls, qcfg: QueryConfig | None = None) -> Retriever:
        """连真栈:复用 pipeline 的 embedding/milvus(检索走本地真栈)。"""
        qcfg = qcfg or load_query_config()
        settings = load_config()
        milvus = MilvusIO(settings)
        milvus.connect()
        return cls(
            EmbeddingClient.from_config(settings), milvus, qcfg,
            hyde_llm=_build_hyde_llm(qcfg), decompose_llm=_build_decompose_llm(qcfg),
        )

    def retrieve(self, query: str, *, include_superseded: bool = False) -> list[Candidate]:
        """§3.3 N3 分解 fan-out:子查询各检索 → 候选并集 → §5.5 重排(原问)→ 取 topk。

        ``_subqueries_for`` 默认 ``[query]``(关/stub)→ 单查询、与既有 byte 等价;仅复合问句
        (decompose 拆 >1)才 fan-out。综合 = 候选并集(保最高分,覆盖各子约束),生成层零改。
        """
        merged: dict[str, Candidate] = {}
        for subquery in self._subqueries_for(query):
            for cid, cand in self._search_candidates(
                subquery, include_superseded=include_superseded
            ).items():
                prev = merged.get(cid)
                if prev is None or cand.score > prev.score:
                    merged[cid] = cand
        ranked = sorted(merged.values(), key=lambda c: c.score, reverse=True)  # RRF 序(none 终态)
        ranked = self._reranker.rerank(query, ranked)  # bge 重排对**原问**;none passthrough(等价)
        return ranked[: self._qcfg.topk]

    def _subqueries_for(self, query: str) -> list[str]:
        """§3.3 N3:decompose 开+gateway → 复合问句拆子查询;否则/单跳/失败 → ``[query]``(直通)。"""
        if self._decompose_llm is None:
            return [query]
        return decompose_subqueries(
            query, self._decompose_llm, max_sub=self._qcfg.decompose_max_sub
        )

    def _search_candidates(
        self, query: str, *, include_superseded: bool = False
    ) -> dict[str, Candidate]:
        """单子查询分区配额检索 → 合并去重(含 §3.1 HyDE / §5.4 sparse)。返回 chunk_id→候选。"""
        with_text = self._qcfg.rerank_backend != "none"  # 仅重排时取 Milvus text(零开销默认)
        emb = self._embed.embed([query])[0]
        dense = self._dense_for(query, emb)    # §3.1 HyDE(关/stub → emb.dense,byte 等价)
        sparse = self._sparse_for(query, emb)  # §5.4 提权/扩展(双关关 → emb.sparse,byte 等价)
        found: dict[str, Candidate] = {}
        for corpus in _PARTITIONS:
            res = self._milvus.search(
                dense,
                sparse,
                topk=self._qcfg.partition_topk,
                include_superseded=include_superseded,
                corpus=corpus,
                with_text=with_text,
            )
            for hit in res.hits:
                cand = _to_candidate(hit, res.retrieval_mode)
                prev = found.get(cand.chunk_id)
                if prev is None or cand.score > prev.score:
                    found[cand.chunk_id] = cand
        return found

    def _dense_for(self, query: str, emb):
        """§3.1 N1 HyDE:hyde 开+gateway → embed(原问+假设性法言)作 dense;否则/失败 → ``emb.dense``。

        ``hyde_llm`` None(关/stub)→ 原问 dense(byte 等价、零网络)。生成失败/返空 → 回落原问
        dense(N1-fail,绝不阻断)。**只改 dense**,sparse 仍走 ``_sparse_for``(§5.4)。
        """
        if self._hyde_llm is None:
            return emb.dense
        text = hyde_dense_text(query, self._hyde_llm)
        return self._embed.embed([text])[0].dense if text else emb.dense

    def _sparse_for(self, query: str, emb) -> dict:
        """§5.4 提权/扩展。双关关 → ``emb.sparse`` 原样(byte 等价 + 只动 sparse)。"""
        if not (self._qcfg.docnum_boost or self._qcfg.scenario_expand):
            return emb.sparse
        return augment_sparse(
            query,
            emb.sparse,
            embed=self._embed,
            scenario_terms=self._scenario_terms,
            docnum_factor=self._qcfg.docnum_boost_factor,
            expand_factor=self._qcfg.scenario_expand_factor,
            docnum_on=self._qcfg.docnum_boost,
            expand_on=self._qcfg.scenario_expand,
        )

    def retrieve_enumerate(
        self, query: str, *, extra_expr: str | None = None, include_superseded: bool = False
    ) -> list[Candidate]:
        """§6.4 枚举模式:**高 k**(``enumerate_partition_topk``/``enumerate_topk``)+ 标量预过滤
        (``extra_expr`` 由 ``listing.build_milvus_expr`` 构,白名单字段)。不激进截断、不改 R1。
        分区配额合并去重(同 chunk_id 保高分)→ 按分降序取 ``enumerate_topk``。
        """
        emb = self._embed.embed([query])[0]
        merged: dict[str, Candidate] = {}
        for corpus in _PARTITIONS:
            res = self._milvus.search(
                emb.dense,
                emb.sparse,
                topk=self._qcfg.enumerate_partition_topk,
                include_superseded=include_superseded,
                corpus=corpus,
                extra_expr=extra_expr,
            )
            for hit in res.hits:
                cand = _to_candidate(hit, res.retrieval_mode)
                prev = merged.get(cand.chunk_id)
                if prev is None or cand.score > prev.score:
                    merged[cand.chunk_id] = cand
        ranked = sorted(merged.values(), key=lambda c: c.score, reverse=True)
        return ranked[: self._qcfg.enumerate_topk]

    def retrieve_cases(self, query: str, *, include_superseded: bool = False) -> list[Candidate]:
        """§6.3 案例分区(P-CASE)语义检索 → 按分降序的 chunk 级候选(``partition_topk`` 条)。

        一案多 chunk(case_summary + case_section)由上层按 ``doc_version_id`` 去重为"一案一卡";
        故此处**不截 topk、不按 dvid 去重**,留足头部供上层去重后仍有足够 distinct 案例。
        ``status==effective`` 前置 + degraded 由上层 ``drop_degraded`` 剔除(沿用 R1 契约)。
        """
        emb = self._embed.embed([query])[0]
        res = self._milvus.search(
            emb.dense,
            emb.sparse,
            topk=self._qcfg.partition_topk,
            include_superseded=include_superseded,
            corpus="P-CASE",
        )
        cands = [_to_candidate(hit, res.retrieval_mode) for hit in res.hits]
        return sorted(cands, key=lambda c: c.score, reverse=True)
