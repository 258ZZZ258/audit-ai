"""§9.3 Langfuse 观测接缝:Protocol + NoopTracer(默认零网络)+ LangfuseTracer(懒导入)+ make_tracer。

**只读旁路**:tracer 绝不改业务态/控制流。**fail-safe**:Langfuse 任何异常吞掉(观测不阻断查询)。
module-level ``_current`` contextvar 串联 graph↔Retriever:``ask()`` 开 trace set,``event()`` 读它把
HyDE/子查询事件挂到同一条 trace。**默认 NoopTracer**(observe 关 / 无 creds)→ 全 no-op、byte 等价。
creds 走 env ``LANGFUSE_PUBLIC_KEY`` / ``LANGFUSE_SECRET_KEY`` / ``LANGFUSE_HOST`` **绝不入库**。
"""

from __future__ import annotations

import contextvars
import os
from contextlib import contextmanager
from typing import Protocol, runtime_checkable

from query.config import QueryConfig

#: 「当前 trace」——ask() 进入 trace 时 set,Retriever.event() 读它挂事件(串联同一条 trace)
_current: contextvars.ContextVar = contextvars.ContextVar("langfuse_trace", default=None)


@runtime_checkable
class Tracer(Protocol):
    """观测接缝:``trace`` 上下文管理(yield span,``update(**f)``)+ ``event`` 挂当前 trace。"""

    def trace(self, name: str, **fields): ...

    def event(self, name: str, **fields) -> None: ...


class _NoopSpan:
    def update(self, **fields) -> None:
        pass


class NoopTracer:
    """默认 tracer:全 no-op(零网络、byte 等价)。observe 关 / 无 creds / langfuse 缺时用它。"""

    @contextmanager
    def trace(self, name: str, **fields):
        yield _NoopSpan()

    def event(self, name: str, **fields) -> None:
        pass


class _LangfuseSpan:
    def __init__(self, trace) -> None:
        self._trace = trace

    def update(self, **fields) -> None:
        try:
            self._trace.update(**fields)
        except Exception:  # noqa: BLE001 — observe 失败绝不阻断查询
            pass


class LangfuseTracer:
    """真 Langfuse tracer:contextvar 串联;**所有 langfuse 调用 fail-safe 吞**。"""

    def __init__(self, client) -> None:
        self._client = client

    @contextmanager
    def trace(self, name: str, **fields):
        try:
            tr = self._client.trace(name=name, **fields)
        except Exception:  # noqa: BLE001 — 建 trace 失败 → 退化 noop span,不阻断
            yield _NoopSpan()
            return
        token = _current.set(tr)
        try:
            yield _LangfuseSpan(tr)
        finally:
            _current.reset(token)
            try:
                self._client.flush()
            except Exception:  # noqa: BLE001
                pass

    def event(self, name: str, **fields) -> None:
        tr = _current.get()
        if tr is None:  # 无当前 trace(Noop / 未开 trace)→ no-op
            return
        try:
            tr.event(name=name, metadata=fields)
        except Exception:  # noqa: BLE001
            pass


def make_tracer(cfg: QueryConfig) -> Tracer:
    """observe 开 + LANGFUSE creds → LangfuseTracer;否则 NoopTracer(关/无 creds/缺 langfuse)。"""
    if not (
        cfg.observe
        and os.environ.get("LANGFUSE_PUBLIC_KEY")
        and os.environ.get("LANGFUSE_SECRET_KEY")
    ):
        return NoopTracer()
    try:
        from langfuse import Langfuse  # 懒导入,默认 noop 路径不需 langfuse(可选 extra)

        return LangfuseTracer(Langfuse())
    except Exception:  # noqa: BLE001 — langfuse 缺/初始化失败 → 退化 Noop,不阻断
        return NoopTracer()
