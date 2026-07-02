"""T11(SPEC-API §6.2):SSE 问答端点。TestClient 读 SSE 流,验事件序列 + 各路由分支 + error。

evidence 路由 monkeypatch ``_evidence_stream`` 喂 canned delta(免真栈/真流式);其余路由用 fake
agent.ask。真栈端到端在 _integration。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from query.api.app import create_app
from query.contract import (
    AnswerBlock,
    BlockType,
    Citation,
    ClauseHit,
    QueryResult,
    RegulationHit,
    RouteType,
    StructuredResult,
    TabPayload,
)

_PREFIX = "/api/query/v1"
_SSE = {"accept": "text/event-stream"}


def _parse_sse(text):
    out = []
    for block in text.strip().split("\n\n"):
        block = block.strip()
        if not block or block.startswith(":"):   # keep-alive 注释帧
            continue
        ev = data = None
        for line in block.split("\n"):
            if line.startswith("event:"):
                ev = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data = line[len("data:"):].strip()
        out.append((ev, json.loads(data) if data else None))
    return out


def _make_result(route=RouteType.CHANGE, **kw):
    return QueryResult(
        route_type=route, ai_label=True,
        answer_blocks=[AnswerBlock(BlockType.TEXT, kw.get("answer", "答复正文……"))],
        citations=kw.get("citations", [Citation(clause_id="c1", doc_title="《细则》")]),
        exhausted_scope=kw.get("exhausted_scope", []),
    )


def _make_structured():
    return StructuredResult(
        regulations=TabPayload(items=[RegulationHit(1, "D", "V", "《细则》", 0.9, "节选")]),
        clauses=TabPayload(items=[ClauseHit(1, "c1", "第六条", "《细则》", "D", 0.98)]),
        regulatory_rules=TabPayload(items=[]),
        cases=TabPayload(items=[]),
    )


class FakeStore:
    def __init__(self):
        self.appended = []

    def get_conversation(self, cid):
        return {"id": cid, "messages": []} if cid == "C1" else None

    def append_message(self, cid, *, role, content=None, **kw):
        self.appended.append({"role": role, "content": content, **kw})
        return f"M{len(self.appended)}"


def _svc(route, result, structured):
    agent = SimpleNamespace(route_only=lambda q: route, ask=lambda q, history=None: result)
    return SimpleNamespace(
        agent=agent, store=FakeStore(), structured_for=lambda q, **kw: structured,
        uploads={}, retriever=None, pg=None, llm=None,
    )


def test_sse_full_sequence_non_evidence():
    svc = _svc(RouteType.CHANGE, _make_result(RouteType.CHANGE), _make_structured())
    r = TestClient(create_app(service=svc)).post(
        f"{_PREFIX}/conversations/C1/messages", json={"query": "变更查询"}, headers=_SSE,
    )
    assert r.status_code == 200 and "text/event-stream" in r.headers["content-type"]
    evs = _parse_sse(r.text)
    kinds = [k for k, _ in evs]
    assert kinds[0] == "accepted" and kinds[-1] == "done"
    for expected in ("route", "structured", "answer_delta", "citations"):
        assert expected in kinds
    assert dict(evs)["route"]["route_type"] == "change"
    assert set(dict(evs)["structured"]) >= {"regulations", "clauses", "regulatory_rules", "cases"}
    done = dict(evs)["done"]
    assert "hit_counts" in done and "elapsed_ms" in done
    assert [a["role"] for a in svc.store.appended] == ["user", "assistant"]   # 落库
    # F2:done 广告的 message_id == 落库 assistant 的 id(前端可据此 GET/导出)
    assert svc.store.appended[1]["message_id"] == done["message_id"]


def test_sse_evidence_streams_real_deltas(monkeypatch):
    import query.api.sse as sse_mod

    result = _make_result(RouteType.EVIDENCE)
    svc = _svc(RouteType.EVIDENCE, result, _make_structured())
    monkeypatch.setattr(
        sse_mod, "_evidence_stream",
        lambda s, q, inc, corpus: iter([("delta", "甲"), ("delta", "乙"), ("result", result)]),
    )
    r = TestClient(create_app(service=svc)).post(
        f"{_PREFIX}/conversations/C1/messages", json={"query": "依据查询"}, headers=_SSE,
    )
    evs = _parse_sse(r.text)
    deltas = [d["text"] for k, d in evs if k == "answer_delta"]
    assert deltas == ["甲", "乙"]              # 真流式逐块喂
    assert [k for k, _ in evs][-1] == "done"


def test_sse_evidence_result_only_refusal_emits_delta(monkeypatch):
    # F10:evidence 路由流式前拒答(result-only,无 delta)→ 补发拒答正文到流,客户端不空
    import query.api.sse as sse_mod

    refuse = _make_result(RouteType.REFUSE, answer="未检索到明确禁止性规定",
                          citations=[], exhausted_scope=["投顾业务"])
    svc = _svc(RouteType.EVIDENCE, refuse, _make_structured())
    monkeypatch.setattr(sse_mod, "_evidence_stream", lambda s, q, i, c: iter([("result", refuse)]))
    r = TestClient(create_app(service=svc)).post(
        f"{_PREFIX}/conversations/C1/messages", json={"query": "二维码开户违规吗"}, headers=_SSE,
    )
    evs = _parse_sse(r.text)
    deltas = "".join(d["text"] for k, d in evs if k == "answer_delta")
    assert "未检索到明确禁止性规定" in deltas          # 拒答正文补发到流
    assert [k for k, _ in evs][-1] == "done"
    assert dict(evs)["done"]["exhausted_scope"] == ["投顾业务"]


def test_sse_refuse_route_carries_exhausted_scope():
    refuse = _make_result(RouteType.REFUSE, answer="未检索到明确禁止性规定",
                          citations=[], exhausted_scope=["投顾业务"])
    svc = _svc(RouteType.REFUSE, refuse, _make_structured())
    r = TestClient(create_app(service=svc)).post(
        f"{_PREFIX}/conversations/C1/messages", json={"query": "无依据"}, headers=_SSE,
    )
    done = dict(_parse_sse(r.text))["done"]
    assert done["exhausted_scope"] == ["投顾业务"]


def test_sse_emits_error_event_on_failure():
    svc = _svc(RouteType.CHANGE, _make_result(), None)

    def boom(*a, **k):
        raise RuntimeError("structured 装配失败")

    svc.structured_for = boom
    r = TestClient(create_app(service=svc)).post(
        f"{_PREFIX}/conversations/C1/messages", json={"query": "q"}, headers=_SSE,
    )
    assert any(k == "error" for k, _ in _parse_sse(r.text))
    # F6:失败态落库(user + assistant route_type=failed),供 history/审计
    assert any(a["role"] == "user" for a in svc.store.appended)
    assert any(a["role"] == "assistant" and a.get("route_type") == "failed"
               for a in svc.store.appended)


def test_sse_user_persisted_even_on_early_failure():
    # F8:被 accepted 的 user 原问在 accepted 前先落 → 即便随后早失败,问题不丢
    svc = _svc(RouteType.CHANGE, _make_result(), _make_structured())

    def boom(_q):
        raise RuntimeError("route 阶段失败")

    svc.agent.route_only = boom
    r = TestClient(create_app(service=svc)).post(
        f"{_PREFIX}/conversations/C1/messages", json={"query": "早失败问句"}, headers=_SSE,
    )
    assert any(k == "error" for k, _ in _parse_sse(r.text))
    assert any(a["role"] == "user" and a["content"] == "早失败问句" for a in svc.store.appended)


def test_evidence_stream_sufficiency_gate_refuses(monkeypatch):
    # F9:充分性闸(与同步一致)—— min_hits 不足 → 覆盖拒答,不流出 evidence 答复
    import query.retrieve.sufficiency as suff_mod
    from query.api.sse import _evidence_stream

    monkeypatch.setattr(
        suff_mod, "assess",
        lambda cands, matters, min_hits=1: SimpleNamespace(sufficient=False),
    )
    svc = SimpleNamespace(
        retriever=SimpleNamespace(retrieve=lambda q, include_superseded=False: []),
        pg=None, llm=None,
        qcfg=SimpleNamespace(sufficiency_min_hits=2, attach_cases=True),
    )
    events = list(_evidence_stream(svc, "费用报销规定", False, None))
    assert [k for k, _ in events] == ["result"]        # 无 delta,直接拒答
    assert events[0][1].route_type is RouteType.REFUSE


def test_sse_persists_raw_query_and_no_double_merge(monkeypatch):
    import query.api.sse as sse_mod

    result = _make_result(RouteType.CHANGE)
    svc = _svc(RouteType.CHANGE, result, _make_structured())
    calls = {}

    def _ask(q, history=None):
        calls["q"] = q
        calls["history"] = history
        return result

    svc.agent.ask = _ask
    monkeypatch.setattr(sse_mod, "_merge", lambda s, q, h: "MERGED-自足问句")
    TestClient(create_app(service=svc)).post(
        f"{_PREFIX}/conversations/C1/messages", json={"query": "它的留痕要求?"}, headers=_SSE,
    )
    # F5:非 evidence 路由 ask 收归并句 + **空 history**(不二次归并)
    assert calls["q"] == "MERGED-自足问句" and calls["history"] == []
    # F5:落库 user 存**原问**(非归并展开句)
    assert svc.store.appended[0]["role"] == "user"
    assert svc.store.appended[0]["content"] == "它的留痕要求?"
