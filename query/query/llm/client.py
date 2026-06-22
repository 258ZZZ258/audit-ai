"""主答/分类 LLM 接缝(Protocol + 工厂)。默认 stub(零网络);gateway 复用 ``pipeline.llm_client``。

镜像 pipeline 接缝 idiom(``orchestration.WorkflowEngine`` / ``parsing.factory``):Protocol + 读
config 选后端 + demo 默认 + 生产对接。与摄取侧"LLM 默认全关"一致——默认 stub **不发任何网络调用**。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from query.config import QueryConfig


@runtime_checkable
class LLMClient(Protocol):
    """结构化对话接口:``chat_json(system, user) -> dict``(与 ``pipeline.llm_client`` 同构)。"""

    def chat_json(self, system: str, user: str) -> dict: ...


def make_llm_client(cfg: QueryConfig) -> LLMClient:
    """按 ``cfg.llm_backend``(默认 ``stub``)返回实现。

    gateway **懒导入** ``pipeline.llm_client``(避免默认装/连网,且 import 期不拉重依赖)。
    """
    backend = cfg.llm_backend
    if backend == "stub":
        from query.llm.stub import StubLLMClient

        return StubLLMClient()
    if backend == "gateway":
        from pipeline.llm_client import make_llm_client as _make_pipeline_llm  # 懒导入,复用 PR#4

        return _make_pipeline_llm(cfg.llm_model)
    raise ValueError(f"未知 QUERY_LLM_BACKEND: {backend!r}(stub | gateway)")
