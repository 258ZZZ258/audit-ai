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
    """本地 bge-reranker-v2-m3(XLM-RoBERTa cross-encoder,懒载;同 BGE-M3 离线,绝不联网)。

    经 ``transformers`` 直载(``AutoModelForSequenceClassification``)打 query×doc 相关性 logit——
    **不走** ``FlagEmbedding.FlagReranker``(其在 transformers 5.x 调已移除的
    ``tokenizer.prepare_for_model``,见 devlog)。``_scores`` 为打分接缝(单测可 mock,免载模型)。
    """

    def __init__(self, model: str) -> None:
        self._model_name = model
        self._loaded: Any = None  # (model, tokenizer),懒载

    def _load(self) -> Any:
        if self._loaded is None:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            # 本地离线契约(SPEC §8 SC6):local_files_only=True 强制只读本地缓存/路径,
            # **绝不联网下载**;模型不在本地 → from_pretrained 抛(fail closed,不静默退化 none)。
            tok = AutoTokenizer.from_pretrained(self._model_name, local_files_only=True)
            mdl = AutoModelForSequenceClassification.from_pretrained(
                self._model_name, local_files_only=True
            )
            mdl.eval()
            self._loaded = (mdl, tok)
        return self._loaded

    def _scores(self, query: str, texts: list[str]) -> list[float]:
        """query×doc cross-encoder 相关性 logit(越大越相关)。打分接缝,单测 mock 之。"""
        import torch

        mdl, tok = self._load()
        with torch.no_grad():
            inp = tok(
                [[query, t] for t in texts],
                padding=True, truncation=True, max_length=512, return_tensors="pt",
            )
            return mdl(**inp).logits.view(-1).tolist()

    def rerank(self, query: str, candidates: list) -> list:
        if not candidates:
            return candidates
        scores = self._scores(query, [getattr(c, "text", None) or "" for c in candidates])
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
