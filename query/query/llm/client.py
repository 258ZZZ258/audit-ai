"""主答/分类 LLM 接缝(Protocol + 工厂)。默认 stub(零网络);gateway 复用 ``pipeline.llm_client``。

镜像 pipeline 接缝 idiom(``orchestration.WorkflowEngine`` / ``parsing.factory``):Protocol + 读
config 选后端 + demo 默认 + 生产对接。与摄取侧"LLM 默认全关"一致——默认 stub **不发任何网络调用**。
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Protocol, runtime_checkable

from query.config import QueryConfig


@runtime_checkable
class LLMClient(Protocol):
    """结构化对话 + 流式接口(与 ``pipeline.llm_client`` 同构)。

    ``chat_json``:结构化输出(引用选择,红线安全);``stream``:逐块 yield 答复正文(§7.2 真流式)。
    """

    def chat_json(self, system: str, user: str) -> dict: ...

    def stream(self, system: str, user: str) -> Iterator[str]: ...


def make_llm_client(cfg: QueryConfig, *, model: str | None = None) -> LLMClient:
    """按 ``cfg.llm_backend``(默认 ``stub``)返回实现。

    gateway **懒导入** ``pipeline.llm_client``(避免默认装/连网,且 import 期不拉重依赖)。
    ``model`` **add-only**:gateway 时用 ``model or cfg.llm_model`` 建客户端——复核传
    ``cfg.review_model``(Kimi)即与主答 ``llm_model``(Qwen)分离(§9.1);**不传 = 主答模型**
    (既有调用零变化)。stub 分支忽略 ``model``(零网络、确定性)。
    """
    backend = cfg.llm_backend
    if backend == "stub":
        from query.llm.stub import StubLLMClient

        return StubLLMClient()
    if backend == "gateway":
        from pipeline.llm_client import make_llm_client as _make_pipeline_llm  # 懒导入,复用 PR#4

        return _make_pipeline_llm(model or cfg.llm_model)
    raise ValueError(f"未知 QUERY_LLM_BACKEND: {backend!r}(stub | gateway)")


def maybe_make_llm_client(
    enabled: bool, cfg: QueryConfig, *, model: str | None = None
) -> LLMClient | None:
    """前端增强(N0 归并 / N1 HyDE / N3 分解 / §9.2 复核)客户端的**离线安全门控**。

    仅 enabled + gateway + 有 OPENAI_API_KEY 时建,否则 ``None``。增强 toggle 默认开,而
    ``make_llm_client(gateway)`` 无 key 即抛 → 直接调用会让 ``from_config`` / 调用期崩溃。
    本门控让缺 key 时降级 no-op(规则版 / 原句 / 单查询 / 主答),而非崩溃。缺 key 是
    ``make_llm_client`` 唯一构造失败,查 key = 查能否构造。**主答 llm 仍 fail-loud**。
    (QUERY-N0/N1/N3-OFFLINE-GATE:增强 toggle 默认开,缺 key 须降级而非崩溃。)
    """
    if enabled and cfg.llm_backend == "gateway" and os.environ.get("OPENAI_API_KEY"):
        return make_llm_client(cfg, model=model)
    return None
