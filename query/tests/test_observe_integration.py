"""T6:§9.3 Langfuse 真观测闭环(门控集成)。

gate = QUERY_OBSERVE + LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY(+ langfuse 装);缺则 skip(不联网)。
聚焦 make_tracer → LangfuseTracer + trace/event/flush 不抛(轻断言,不依赖 server 回读)。
本地无 creds → skip(诚实记 🟡,待真 Langfuse 跑绿翻 ✅)。

运行:
    pip install -e "query[observe]"
    QUERY_OBSERVE=1 LANGFUSE_PUBLIC_KEY=*** LANGFUSE_SECRET_KEY=*** LANGFUSE_HOST=<host> \
      .venv/bin/python -m pytest query/tests/test_observe_integration.py -q
"""

from __future__ import annotations

import os

import pytest

from query.config import QueryConfig
from query.observe import LangfuseTracer, make_tracer


@pytest.fixture
def tracer():
    if not (
        os.environ.get("QUERY_OBSERVE")
        and os.environ.get("LANGFUSE_PUBLIC_KEY")
        and os.environ.get("LANGFUSE_SECRET_KEY")
    ):
        pytest.skip("未设 QUERY_OBSERVE + LANGFUSE_* creds——§9.3 真观测门控跳过(绝不联网)")
    t = make_tracer(QueryConfig(observe=True))
    if not isinstance(t, LangfuseTracer):
        pytest.skip("langfuse 未安装(可选 extra)——真观测门控跳过")
    return t


def test_real_langfuse_trace_event_flush(tracer):
    # 真 Langfuse:开 trace → 挂 event → update → flush,全程不抛(观测闭环)。
    with tracer.trace("query-test", input="二维码开户违规吗") as span:
        tracer.event("hyde", passage="经营机构不得违规招揽客户。")
        tracer.event("decompose", subqueries=["q1", "q2"])
        span.update(output="judgmental", metadata={"route_type": "judgmental"})
    # 未抛即闭环成立(不依赖 server 回读)
