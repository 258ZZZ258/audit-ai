"""observe 单元(零栈零网络):Tracer 接缝 + Retriever/ask 发 event(T2 核心 + T4/T5 接线)。

tracer 只读旁路:绝不改业务态/控制流;Langfuse 任何异常 fail-safe 吞;contextvar 串联 graph↔Retriever。
默认 NoopTracer → 全 no-op、零网络、byte 等价。
"""

from __future__ import annotations

import sys
import types

from query.config import QueryConfig
from query.observe import LangfuseTracer, NoopTracer, make_tracer


class _FakeTrace:
    def __init__(self) -> None:
        self.updates: list = []
        self.events: list = []
        self.input = None

    def update(self, **f):
        self.updates.append(f)

    def event(self, **f):
        self.events.append(f)


class _FakeClient:
    def __init__(self, *, raise_trace: bool = False) -> None:
        self.flushed = 0
        self.traces: list = []
        self._raise = raise_trace

    def trace(self, **f):
        if self._raise:
            raise RuntimeError("langfuse boom")
        t = _FakeTrace()
        t.input = f
        self.traces.append(t)
        return t

    def flush(self):
        self.flushed += 1


# ── T2:NoopTracer / make_tracer / LangfuseTracer / contextvar / fail-safe ─────
def test_noop_tracer_no_op():
    t = NoopTracer()
    with t.trace("query", input="x") as span:
        span.update(output="y")  # 不抛
    t.event("hyde", passage="p")  # 不抛(无当前 trace 也无所谓)


def test_make_tracer_off_or_no_creds_returns_noop(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    assert isinstance(make_tracer(QueryConfig(observe=False)), NoopTracer)  # 关
    assert isinstance(make_tracer(QueryConfig(observe=True)), NoopTracer)   # 开但无 creds


def test_make_tracer_on_with_creds_returns_langfuse(monkeypatch):
    fake_mod = types.ModuleType("langfuse")
    fake_mod.Langfuse = lambda *a, **k: _FakeClient()
    monkeypatch.setitem(sys.modules, "langfuse", fake_mod)
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    assert isinstance(make_tracer(QueryConfig(observe=True)), LangfuseTracer)


def test_langfuse_tracer_records_event_and_flushes():
    client = _FakeClient()
    t = LangfuseTracer(client)
    with t.trace("query", input="q") as span:
        t.event("hyde", passage="p")       # 挂当前 trace(contextvar)
        span.update(output="evidence")
    tr = client.traces[0]
    assert tr.input == {"name": "query", "input": "q"}          # trace 建
    assert tr.events == [{"name": "hyde", "metadata": {"passage": "p"}}]  # event 挂上
    assert tr.updates == [{"output": "evidence"}]
    assert client.flushed == 1                                  # 收口 flush


def test_event_noop_outside_trace():
    LangfuseTracer(_FakeClient()).event("hyde", passage="p")  # 无当前 trace → no-op,不抛


def test_langfuse_tracer_failsafe_on_trace_error():
    t = LangfuseTracer(_FakeClient(raise_trace=True))
    with t.trace("query", input="q") as span:  # client.trace 抛 → 退化 noop span,不传播
        span.update(output="x")                 # 不抛
        t.event("hyde", passage="p")            # 不抛


# ── T4:Retriever 持 tracer + 发 hyde/decompose event(只读旁路,fake tracer)──────
class _CaptureTracer:
    def __init__(self) -> None:
        self.events: list = []

    def trace(self, name, **f):  # Retriever 不开 trace,留接口完整
        return NoopTracer().trace(name, **f)

    def event(self, name, **f) -> None:
        self.events.append((name, f))


class _Emb:
    def __init__(self, dense, sparse) -> None:
        self.dense = dense
        self.sparse = sparse


class _FakeEmbed:
    def __init__(self) -> None:
        self.texts: list = []

    def embed(self, texts):
        self.texts.extend(texts)
        return [_Emb([float(len(t))], {1: 1.0}) for t in texts]


class _FakeLLM:
    def __init__(self, resp) -> None:
        self._resp = resp

    def chat_json(self, system, user):
        return self._resp


def _retriever(*, tracer=None, hyde_llm=None, decompose_llm=None):
    from query.config import load_query_config
    from query.retrieve.hybrid import Retriever

    return Retriever(
        _FakeEmbed(), None, load_query_config(),
        hyde_llm=hyde_llm, decompose_llm=decompose_llm, tracer=tracer,
    )


def test_dense_for_emits_hyde_event():
    cap = _CaptureTracer()
    r = _retriever(tracer=cap, hyde_llm=_FakeLLM({"passage": "经营机构不得违规招揽客户。"}))
    emb = r._embed.embed(["二维码开户违规吗"])[0]
    r._dense_for("二维码开户违规吗", emb)
    assert cap.events == [("hyde", {"passage": "二维码开户违规吗\n经营机构不得违规招揽客户。"})]


def test_subqueries_for_emits_decompose_event():
    cap = _CaptureTracer()
    r = _retriever(tracer=cap, decompose_llm=_FakeLLM({"subqueries": ["q1", "q2"]}))
    assert r._subqueries_for("复合问句") == ["q1", "q2"]
    assert cap.events == [("decompose", {"subqueries": ["q1", "q2"]})]


def test_retriever_noop_default_no_events():
    # 不传 tracer(默认 Noop)→ _dense_for/_subqueries_for 不发 event、返回值不变(byte 等价)
    r = _retriever(
        hyde_llm=_FakeLLM({"passage": "P"}),
        decompose_llm=_FakeLLM({"subqueries": ["a", "b"]}),
    )
    emb = r._embed.embed(["q"])[0]
    r._embed.texts.clear()
    assert r._dense_for("q", emb) == r._embed.embed(["q\nP"])[0].dense  # HyDE 照常
    assert r._subqueries_for("q") == ["a", "b"]  # 分解照常;无 tracer 不抛
