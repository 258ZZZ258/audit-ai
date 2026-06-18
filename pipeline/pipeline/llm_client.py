"""最小 OpenAI 兼容 LLM client(httpx)。E2 打标 / L2 元数据 / 案例摘要等 LLM 辅助共用。

env(运行期、**绝不入库**):``OPENAI_API_KEY``(必填)/ ``OPENAI_BASE_URL``(默认
``https://api.openai.com/v1``)/ ``OPENAI_MODEL``(默认 ``gpt-5.4-nano``)。
**默认零调用**——仅在 ``e2_enabled`` 等开关开启时被构造;关闭时管线路径不触达本模块。
"""

from __future__ import annotations

import json
import os
import time

import httpx

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-5.4-nano"


class LLMError(RuntimeError):
    """LLM 调用失败(重试耗尽 / 配置缺失 / 响应不可解析)。"""


class LLMClient:
    """OpenAI 兼容 chat/completions 客户端(支持 JSON 模式;瞬时错误指数退避 ×retries)。"""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout: float = 60.0,
        retries: int = 3,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self.model = model
        self._timeout = timeout
        self._retries = retries

    def chat(self, messages: list[dict], *, json_mode: bool = False) -> str:
        payload: dict = {"model": self.model, "messages": messages}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        last: Exception | None = None
        for attempt in range(self._retries):
            try:
                resp = httpx.post(
                    f"{self._base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=payload,
                    timeout=self._timeout,
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
            except Exception as e:  # 瞬时错误指数退避(§8.1 同款);耗尽抛 LLMError
                last = e
                if attempt < self._retries - 1:
                    time.sleep(2**attempt)
        raise LLMError(f"LLM 调用失败(retries={self._retries}): {last}")

    def chat_json(self, system: str, user: str) -> dict:
        """system + user → JSON 模式 → 解析为 dict(响应非合法 JSON 抛 LLMError)。"""
        raw = self.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            json_mode=True,
        )
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise LLMError(f"LLM 响应非合法 JSON: {raw[:200]!r}") from e


def make_llm_client(model: str | None = None) -> LLMClient:
    """从 env 构造;``OPENAI_API_KEY`` 缺失即抛(LLM 默认关,启用时须经 env 提供 key)。"""
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise LLMError("OPENAI_API_KEY 未设置——LLM 辅助默认关;启用时须经 env 提供 key(绝不入库)")
    return LLMClient(
        api_key=key,
        base_url=os.environ.get("OPENAI_BASE_URL", DEFAULT_BASE_URL),
        model=model or os.environ.get("OPENAI_MODEL", DEFAULT_MODEL),
    )
