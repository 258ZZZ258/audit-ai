"""§5.5 重排接缝:Protocol + demo 默认(none passthrough)+ 本地 bge-reranker + factory。

镜像 ``llm/client.py`` / ``embedding_client`` 接缝。``none`` **默认** = passthrough(保 RRF 序,
``rerank=none`` byte 等价);``bge`` = 本地 ``FlagReranker`` 懒载(同 BGE-M3,首次 rerank 时载)。
候选按 ``.text`` 做 cross-encoder 打分。加载失败**抛、不静默退化 none**(避免误以为重排了)。
模块级零 pipeline 导入(候选按 ``.text`` 鸭子类型,不引 ``Candidate``)。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class RerankerClient(Protocol):
    """重排接口:``rerank(query, candidates) -> 重排后 candidates``(候选需带 ``.text``)。"""

    def rerank(self, query: str, candidates: list) -> list: ...


class NoneReranker:
    """passthrough:保留入参(RRF)序 → ``rerank=none`` byte 等价(demo 默认)。"""

    def rerank(self, query: str, candidates: list) -> list:
        return candidates


class BGEReranker:
    """本地 bge-reranker-v2-m3(``FlagReranker``,懒载;同 BGE-M3 离线,绝不联网)。"""

    def __init__(self, model: str) -> None:
        self._model_name = model
        self._reranker: Any = None

    def _model(self) -> Any:
        if self._reranker is None:
            from FlagEmbedding import FlagReranker  # 懒载,避免 import 期拉模型

            self._reranker = FlagReranker(self._model_name, use_fp16=True)
        return self._reranker

    def rerank(self, query: str, candidates: list) -> list:
        if not candidates:
            return candidates
        pairs = [(query, getattr(c, "text", None) or "") for c in candidates]
        scores = self._model().compute_score(pairs)
        if not isinstance(scores, list):  # compute_score 单对可能返标量
            scores = [scores]
        order = sorted(zip(scores, candidates, strict=True), key=lambda z: z[0], reverse=True)
        return [c for _, c in order]


def make_reranker(qcfg) -> RerankerClient:
    """按 ``qcfg.rerank_backend``(默认 none)返回实现(同 LLM/embedding factory)。"""
    backend = getattr(qcfg, "rerank_backend", "none")
    if backend == "none":
        return NoneReranker()
    if backend == "bge":
        return BGEReranker(getattr(qcfg, "rerank_model", "BAAI/bge-reranker-v2-m3"))
    raise ValueError(f"未知 QUERY_RERANK_BACKEND: {backend!r}(none | bge)")
