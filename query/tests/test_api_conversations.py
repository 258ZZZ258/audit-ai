"""T5(SPEC-API §3/§7):会话端点。TestClient + 注入 FakeStore(免真栈)。

覆盖:新会话(201)、列表分页 + 标题搜索、详情(用户问题/系统摘要/统计卡)、404、删除、
page_size>100→422。
"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from query.api.app import create_app
from query.session.store import paginate

_PREFIX = "/api/query/v1"


class FakeStore:
    def __init__(self) -> None:
        self._conv: dict = {}
        self._msgs: dict = {}
        self._n = 0

    def create_conversation(self, *, agent_type="institution_query", asker_role=None, title=None):
        self._n += 1
        cid = f"C{self._n}"
        self._conv[cid] = {
            "id": cid, "title": title, "agent_type": agent_type, "asker_role": asker_role,
            "created_at": "2026-07-01T10:00:00", "updated_at": "2026-07-01T10:00:00",
            "message_count": 0, "last_hit_counts": None,
        }
        self._msgs[cid] = []
        return cid

    def list_conversations(self, *, page=1, page_size=20, q=None):
        rows = list(self._conv.values())
        if q:
            rows = [r for r in rows if q in (r["title"] or "")]
        total = len(rows)
        start = (page - 1) * page_size
        page_rows = rows[start:start + page_size]
        return {"data": page_rows, "pagination": paginate(page, page_size, total)}

    def get_conversation(self, cid):
        c = self._conv.get(cid)
        if c is None:
            return None
        return {**c, "messages": self._msgs[cid]}

    def delete_conversation(self, cid):
        self._msgs.pop(cid, None)
        return self._conv.pop(cid, None) is not None

    def add_msg(self, cid, role, content, **kw):
        seq = len(self._msgs[cid]) + 1
        self._msgs[cid].append({"role": role, "content": content, "seq": seq, **kw})


def _client():
    store = FakeStore()
    return TestClient(create_app(service=SimpleNamespace(store=store))), store


def test_create_returns_201_and_list_search():
    c, _ = _client()
    r = c.post(f"{_PREFIX}/conversations", json={"title": "融资融券适当性依据"})
    assert r.status_code == 201
    cid = r.json()["id"]
    # 建第二个不匹配搜索词的会话
    c.post(f"{_PREFIX}/conversations", json={"title": "反洗钱尽调"})
    r = c.get(f"{_PREFIX}/conversations", params={"q": "融资融券"})
    body = r.json()
    assert body["pagination"]["total_items"] == 1
    assert [x["id"] for x in body["data"]] == [cid]


def test_list_pagination_shape():
    c, store = _client()
    for i in range(25):
        store.create_conversation(title=f"会话{i}")
    r = c.get(f"{_PREFIX}/conversations", params={"page": 2, "page_size": 10})
    pg = r.json()["pagination"]
    assert pg == {"page": 2, "page_size": 10, "total_items": 25, "total_pages": 3}
    assert len(r.json()["data"]) == 10


def test_detail_user_question_summary_and_stat_cards():
    c, store = _client()
    cid = store.create_conversation(asker_role="审计人员", title="融资融券依据")
    store.add_msg(cid, "user", "融资融券客户适当性制度依据")
    store.add_msg(cid, "assistant", "已检索到相关制度与案例…", route_type="evidence")
    hits = {"regulations": 3, "clauses": 8, "regulatory_rules": 2, "cases": 4}
    store._conv[cid]["last_hit_counts"] = hits
    d = c.get(f"{_PREFIX}/conversations/{cid}").json()
    assert d["user_question"] == "融资融券客户适当性制度依据"
    assert d["summary"] == "已检索到相关制度与案例…"
    assert d["hit_counts"] == hits
    assert len(d["messages"]) == 2 and d["asker_role"] == "审计人员"


def test_detail_and_delete_404():
    c, store = _client()
    assert c.get(f"{_PREFIX}/conversations/NOPE").status_code == 404
    cid = store.create_conversation(title="t")
    assert c.delete(f"{_PREFIX}/conversations/{cid}").status_code == 200
    assert c.delete(f"{_PREFIX}/conversations/{cid}").status_code == 404  # 已删


def test_page_size_over_100_returns_422():
    c, _ = _client()
    r = c.get(f"{_PREFIX}/conversations", params={"page_size": 200})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
