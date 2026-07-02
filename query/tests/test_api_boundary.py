"""audit-biz 边界二 ``POST /v1/query``:无身份、无状态、SSE 五事件、前置过滤。"""

from __future__ import annotations

import json
from contextlib import contextmanager

from fastapi.testclient import TestClient

from query.api.app import create_app
from query.contract import AnswerBlock, BlockType, Citation, QueryResult, RouteType
from query.retrieve.hybrid import Candidate


def _parse_sse(text):
    out = []
    for block in text.strip().split("\n\n"):
        event = data = None
        for line in block.split("\n"):
            if line.startswith("event:"):
                event = line[len("event:"):].strip()
            if line.startswith("data:"):
                data = line[len("data:"):].strip()
        if event:
            out.append((event, json.loads(data)))
    return out


class _Agent:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def ask(self, query, history=None, *, trace_id=None):
        self.calls.append({"query": query, "history": history, "trace_id": trace_id})
        return self.result


class _Retriever:
    def __init__(self):
        self.scopes = []

    @contextmanager
    def scoped(self, **scope):
        self.scopes.append(scope)
        yield

    def retrieve(self, query, *, include_superseded=False):
        return [
            Candidate("c1", 0.9, "P-INT", "DV1", "1/1", 1, False, "hybrid"),
            Candidate("c2", 0.1, "P-INT", "DV2", "1/2", 1, False, "hybrid"),
        ]

    def retrieve_cases(self, query, *, include_superseded=False):
        return []


class _Svc:
    def __init__(self):
        self.agent = _Agent(
            QueryResult(
                route_type=RouteType.EVIDENCE,
                answer_blocks=[AnswerBlock(BlockType.TEXT, "答复")],
                citations=[Citation("c1", doc_title="不应出边界")],
                confidence=0.8,
            )
        )
        self.retriever = _Retriever()


def _client(monkeypatch, svc=None):
    monkeypatch.setenv("AUDIT_AI_INTERNAL_TOKEN", "secret")
    return TestClient(create_app(service=svc or _Svc()))


def _body(**overrides):
    body = {
        "query": "客户适当性依据",
        "request_id": "REQ-1",
        "filters": {
            "perm_tags": ["内部"],
            "corpus_types": ["internal"],
            "project_id": None,
            "owner": "ignored-for-regulations",
        },
        "options": {"top_k": 5, "include_superseded": False},
    }
    body.update(overrides)
    return body


def test_boundary_requires_internal_token(monkeypatch):
    c = _client(monkeypatch)
    r = c.post("/v1/query", json=_body())
    assert r.status_code == 401
    assert r.json() == {"error": {"code": "B104", "message": "内部令牌无效"}}


def test_boundary_sse_maps_query_result_to_five_event_vocab(monkeypatch):
    svc = _Svc()
    r = _client(monkeypatch, svc).post(
        "/v1/query", json=_body(), headers={"X-Internal-Token": "secret"}
    )
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    events = _parse_sse(r.text)
    assert [e for e, _ in events] == ["meta", "delta", "citation", "done"]

    data = dict(events)
    assert data["meta"]["request_id"] == "REQ-1"
    assert data["meta"]["route_type"] == "evidence"
    assert data["delta"] == {"block_seq": 0, "block_type": "text", "text": "答复"}
    # 轻量引用:只回 clause_id/chunk_id/score,不泄 doc_title/page/version 等回查字段。
    assert data["citation"] == {"clause_id": "c1", "chunk_id": "c1", "score": 1.0}
    assert data["done"]["finish_reason"] == "stop"
    assert svc.agent.calls[0]["trace_id"] == "REQ-1"


def test_boundary_filters_are_scoped_before_retrieval(monkeypatch):
    svc = _Svc()
    _client(monkeypatch, svc).post(
        "/v1/query", json=_body(), headers={"X-Internal-Token": "secret"}
    )
    scope = svc.retriever.scopes[0]
    assert scope["corpora"] == ("P-INT",)
    assert scope["topk"] == 5 and scope["partition_topk"] == 5
    assert scope["extra_expr"] == 'array_contains_any(perm_tag, ["内部"])'
    assert "owner" not in scope["extra_expr"]  # owner 不作用于制度语料


def test_boundary_rejects_audit_project_owner_until_schema_exists(monkeypatch):
    body = _body(
        filters={
            "perm_tags": [],
            "corpus_types": ["audit_project"],
            "project_id": "P1",
            "owner": "u1",
        }
    )
    r = _client(monkeypatch).post(
        "/v1/query", json=body, headers={"X-Internal-Token": "secret"}
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_retriever_scope_threads_filter_to_milvus():
    from query.config import QueryConfig
    from query.retrieve.hybrid import Retriever

    class _Emb:
        dense = [0.1]
        sparse = {1: 1.0}

    class _Embed:
        def embed(self, texts):
            return [_Emb()]

    class _Milvus:
        def __init__(self):
            self.calls = []

        def search(self, dense, sparse, **kw):
            self.calls.append(kw)
            return type("R", (), {"hits": [], "retrieval_mode": "hybrid"})()

    milvus = _Milvus()
    retriever = Retriever(_Embed(), milvus, QueryConfig(decompose=False, hyde=False))
    with retriever.scoped(
        corpora=("P-INT",), extra_expr='array_contains_any(perm_tag, ["内部"])',
        topk=3, partition_topk=3,
    ):
        assert retriever.retrieve("q") == []
    assert milvus.calls == [{
        "topk": 3,
        "include_superseded": False,
        "corpus": "P-INT",
        "extra_expr": 'array_contains_any(perm_tag, ["内部"])',
        "with_text": False,
    }]
