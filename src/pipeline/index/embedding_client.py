"""嵌入客户端:抽象接口 + 本地 BGEM3 实现(dense+sparse 一次产出)+ endpoint env 桩。

本地用 FlagEmbedding ``BGEM3FlagModel``:一次 ``encode`` 同出 dense(归一,1024 维)+ sparse
(``lexical_weights``,token_id→权重)。模型**懒加载**(首次 embed 时载;首跑从 HF 下载 ~2GB)。
batch_size / max_length / retries 全部从 config(⚠)。指数退避重试编码调用。
endpoint(OpenAI 兼容)留 env 桩:M1 不要求跑(且仅 dense,无 BGE-M3 的单次 dense+sparse 语义)。

sparse 的 token_id→SPARSE_FLOAT_VECTOR 转换属 C5(milvus_io);本层只产出原始 lexical_weights。
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pipeline.config import EmbeddingConfig, Settings


@dataclass(frozen=True)
class Embedding:
    dense: list[float]  # 归一稠密向量(BGE-M3 1024 维)
    sparse: dict[str, float]  # lexical_weights:token_id(str)→权重(C5 转 SPARSE_FLOAT_VECTOR)


def _retry(fn: Callable[[], Any], *, retries: int) -> Any:
    """指数退避重试 ``fn()``;末次仍失败则抛最后一次异常。"""
    last: Exception | None = None
    for i in range(max(1, retries)):
        try:
            return fn()
        except Exception as e:  # 重试任何编码失败(OOM/瞬时错误)
            last = e
            if i < retries - 1:
                time.sleep(0.5 * 2**i)
    raise last if last else RuntimeError("retry 未执行")


class EmbeddingClient(ABC):
    """嵌入客户端接口。``embed`` 接收文本列表,返回等长 ``Embedding`` 列表。"""

    @abstractmethod
    def embed(self, texts: list[str]) -> list[Embedding]: ...

    @classmethod
    def from_config(cls, settings: Settings) -> EmbeddingClient:
        cfg = settings.embedding
        return LocalBGEM3Client(cfg) if cfg.mode == "local" else EndpointClient(cfg)


class LocalBGEM3Client(EmbeddingClient):
    def __init__(self, cfg: EmbeddingConfig) -> None:
        self.cfg = cfg
        self._model: Any = None  # 懒加载(避免 import 期加载 ~2GB 模型)

    def _load(self) -> Any:
        if self._model is None:
            from FlagEmbedding import BGEM3FlagModel

            self._model = BGEM3FlagModel(self.cfg.model_name, use_fp16=False)  # CPU 友好
        return self._model

    def embed(self, texts: list[str]) -> list[Embedding]:
        if not texts:
            return []
        model = self._load()
        out = _retry(
            lambda: model.encode(
                texts,
                batch_size=self.cfg.batch_size,
                max_length=self.cfg.max_length,
                return_dense=True,
                return_sparse=True,
                return_colbert_vecs=False,
            ),
            retries=self.cfg.retries,
        )
        dense, sparse = out["dense_vecs"], out["lexical_weights"]
        return [
            Embedding(
                dense=[float(x) for x in dense[i]],
                sparse={str(k): float(v) for k, v in sparse[i].items()},
            )
            for i in range(len(texts))
        ]


class EndpointClient(EmbeddingClient):
    """OpenAI 兼容 endpoint 桩:M1 不要求跑(仅 dense,无 BGE-M3 sparse)。"""

    def __init__(self, cfg: EmbeddingConfig) -> None:
        self.cfg = cfg

    def embed(self, texts: list[str]) -> list[Embedding]:
        raise NotImplementedError("endpoint 嵌入 M1 留桩(仅 dense);用 mode=local 跑 BGE-M3")
