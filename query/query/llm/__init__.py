"""LLM 接缝:Protocol + 工厂(默认 stub 零网络,gateway 复用 pipeline.llm_client)。"""

from query.llm.client import LLMClient, make_llm_client

__all__ = ["LLMClient", "make_llm_client"]
