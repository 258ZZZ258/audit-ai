"""T3(SPEC-API §7):会话持久化 store。

离线单测:``paginate`` 纯函数 + 模型结构(表名/列/FK CASCADE)。
集成:CRUD 往返 —— gate=PG + query_* 表已迁移(0012);离线/未迁移即 skip(合并门 demo up 后跑)。
"""

from __future__ import annotations

import uuid

import pytest

from common.pg_models import QueryConversation, QueryMessage
from query.session.store import SessionStore, paginate


# ── 离线单测 ─────────────────────────────────────────────────────────────────
def test_paginate_math():
    assert paginate(1, 20, 68) == {
        "page": 1, "page_size": 20, "total_items": 68, "total_pages": 4,
    }
    assert paginate(1, 20, 0)["total_pages"] == 0           # 空 → 0 页
    assert paginate(2, 25, 50)["total_pages"] == 2          # 整除
    p = paginate(0, 0, 5)                                   # 越界归一到 ≥1
    assert p["page"] == 1 and p["page_size"] == 1


def test_models_tablenames_columns_and_fk():
    assert QueryConversation.__tablename__ == "query_conversations"
    assert QueryMessage.__tablename__ == "query_messages"
    conv_cols = QueryConversation.__table__.columns
    for c in ("id", "title", "agent_type", "asker_role", "message_count",
              "last_hit_counts", "created_at", "updated_at"):
        assert c in conv_cols
    msg_cols = QueryMessage.__table__.columns
    for c in ("id", "conversation_id", "seq", "role", "content", "route_type",
              "result_json", "hit_counts", "elapsed_ms", "ai_label"):
        assert c in msg_cols
    fk = next(iter(QueryMessage.__table__.c.conversation_id.foreign_keys))
    assert fk.column.table.name == "query_conversations"
    assert fk.ondelete == "CASCADE"   # 删会话级联删消息


# ── 集成(PG + 0012 迁移;离线 skip)──────────────────────────────────────────
@pytest.fixture
def store():
    from sqlalchemy import text

    from pipeline.config import load_config
    from pipeline.index.pg_io import PgIO

    pg = PgIO.from_config(load_config())
    try:
        with pg.session() as s:
            s.execute(text("select 1 from query_conversations limit 1"))
    except Exception:
        pytest.skip("PG 不可达或 query_* 表未迁移(0012);合并门 demo up 后跑")
    return SessionStore(pg)


def test_store_crud_roundtrip(store):
    marker = uuid.uuid4().hex[:8]
    cid = store.create_conversation(title=f"融资融券适当性依据 {marker}", asker_role="审计人员")
    try:
        store.append_message(cid, role="user", content="融资融券客户适当性制度依据")
        mid = store.append_message(
            cid, role="assistant", content="已检索到相关制度与案例…", route_type="evidence",
            result_json={"route_type": "evidence"},
            hit_counts={"regulations": 3, "clauses": 8}, elapsed_ms=2300,
        )
        # 列表 + 标题搜索(marker 唯一 → 恰命中本会话)
        listed = store.list_conversations(page=1, page_size=20, q=marker)
        assert [c["id"] for c in listed["data"]] == [cid]
        assert listed["pagination"]["total_items"] == 1
        conv = listed["data"][0]
        assert conv["message_count"] == 2
        assert conv["last_hit_counts"] == {"regulations": 3, "clauses": 8}  # 统计卡冗余
        # 详情:消息按 seq 序,user 在前
        detail = store.get_conversation(cid)
        assert len(detail["messages"]) == 2
        assert detail["messages"][0]["role"] == "user"
        assert detail["messages"][1]["route_type"] == "evidence"
        # 单条完整快照(result_json 供导出/查看详情)
        full = store.get_message(mid)
        assert full["result_json"] == {"route_type": "evidence"} and full["elapsed_ms"] == 2300
        # append 到不存在会话 → KeyError
        with pytest.raises(KeyError):
            store.append_message("NONEXISTENT_CID", role="user", content="x")
    finally:
        assert store.delete_conversation(cid) is True   # 级联删消息
    assert store.get_conversation(cid) is None           # 删后不可见
