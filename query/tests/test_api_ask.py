"""T6(SPEC-API §6):问答端点(同步 JSON)。TestClient + fake svc(store/agent/structured_for)。

覆盖:evidence 返 structured 四-Tab + citations + meta;落 user+assistant;query>2000→422;
会话 404;附件不存在→422;corpus 非法→422;history 传入 agent;refuse 路由。
"""

from __future__ import annotations

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


class FakeStore:
    def __init__(self) -> None:
        self.msgs: dict = {}
        self.appended: list = []

    def create(self, cid, messages=None):
        self.msgs[cid] = list(messages or [])

    def get_conversation(self, cid):
        return {"id": cid, "messages": self.msgs[cid]} if cid in self.msgs else None

    def append_message(self, cid, *, role, content=None, **kw):
        self.appended.append({"cid": cid, "role": role, "content": content, **kw})
        return f"M{len(self.appended)}"


class FakeAgent:
    def __init__(self, result):
        self._result = result
        self.last_history = None

    def ask(self, query, history=None):
        self.last_history = history
        return self._result


def _make_result(route=RouteType.EVIDENCE):
    return QueryResult(
        route_type=route, ai_label=True,
        answer_blocks=[AnswerBlock(BlockType.TEXT, "已检索到相关制度与案例…")],
        citations=[Citation(clause_id="c1", doc_title="《细则》")],
    )


def _make_structured():
    return StructuredResult(
        regulations=TabPayload(items=[RegulationHit(1, "D", "V", "《细则》", 0.9, "节选")]),
        clauses=TabPayload(items=[ClauseHit(1, "c1", "第六条", "《细则》", "D", 0.98)]),
        regulatory_rules=TabPayload(items=[]),
        cases=TabPayload(items=[]),
    )


class FakeService:
    def __init__(self, result=None):
        self.store = FakeStore()
        self.agent = FakeAgent(result or _make_result())
        self.uploads = {"up1": {}}
        self._structured = _make_structured()

    def structured_for(self, query, *, include_superseded=False, corpus=None):
        return self._structured


def _client(svc=None):
    svc = svc or FakeService()
    return TestClient(create_app(service=svc)), svc


def test_ask_returns_structured_citations_meta_and_persists():
    c, svc = _client()
    svc.store.create("C1")
    r = c.post(f"{_PREFIX}/conversations/C1/messages", json={"query": "融资融券客户适当性依据"})
    assert r.status_code == 200
    body = r.json()
    assert body["route_type"] == "evidence"
    assert body["structured"]["regulations"]["total"] == 1
    assert body["structured"]["clauses"]["items"][0]["clause_id"] == "c1"
    assert body["citations"][0]["clause_id"] == "c1"
    assert body["meta"]["hit_counts"] == {
        "regulations": 1, "clauses": 1, "regulatory_rules": 0, "cases": 0,
    }
    assert body["meta"]["total_hits"] == 2 and "elapsed_ms" in body["meta"]
    # 落库:user 在前,assistant 带 route_type + 契约快照
    assert [a["role"] for a in svc.store.appended] == ["user", "assistant"]
    assistant = svc.store.appended[1]
    assert assistant["route_type"] == "evidence"
    assert assistant["result_json"]["route_type"] == "evidence"
    assert assistant["hit_counts"]["clauses"] == 1


def test_query_over_2000_returns_422():
    c, svc = _client()
    svc.store.create("C1")
    r = c.post(f"{_PREFIX}/conversations/C1/messages", json={"query": "x" * 2001})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert svc.store.appended == []   # 校验失败不落库


def test_conversation_not_found_404():
    c, _ = _client()
    r = c.post(f"{_PREFIX}/conversations/NOPE/messages", json={"query": "q"})
    assert r.status_code == 404


def test_bad_attachment_returns_422():
    c, svc = _client()
    svc.store.create("C1")
    r = c.post(
        f"{_PREFIX}/conversations/C1/messages",
        json={"query": "q", "attachments": ["missing"]},
    )
    assert r.status_code == 422
    assert "missing" in str(r.json()["error"].get("details"))


def test_invalid_corpus_returns_422():
    c, svc = _client()
    svc.store.create("C1")
    r = c.post(f"{_PREFIX}/conversations/C1/messages", json={"query": "q", "corpus": "qa"})
    assert r.status_code == 422


def test_history_passed_to_agent():
    svc = FakeService()
    prior = [
        {"role": "user", "content": "上一问"},
        {"role": "assistant", "content": "上一答"},
    ]
    svc.store.create("C1", messages=prior)
    c, _ = _client(svc)
    c.post(f"{_PREFIX}/conversations/C1/messages", json={"query": "追问"})
    assert svc.agent.last_history == prior


def test_refuse_route_still_returns_contract():
    svc = FakeService(result=_make_result(RouteType.REFUSE))
    svc.store.create("C1")
    c, _ = _client(svc)
    r = c.post(f"{_PREFIX}/conversations/C1/messages", json={"query": "无依据问句"})
    assert r.status_code == 200 and r.json()["route_type"] == "refuse"
    assert svc.store.appended[1]["route_type"] == "refuse"
