"""T3(SPEC-API §7):会话持久化 store(over ``PgIO``)。

CRUD + 分页 + 标题搜索 + 级联删 + append_message。返回**脱离会话的 dict**(避 DetachedInstance),
API 层(T5)直接序列化 / 派生系统摘要。``paginate`` 为纯函数(离线可测)。**单向只读红线**:只写
``query_*`` 表,绝不回写 corpus 权威表。
"""

from __future__ import annotations

import math

from sqlalchemy import delete, func, select
from ulid import ULID

from common.pg_models import QueryConversation, QueryMessage


def paginate(page: int, page_size: int, total_items: int) -> dict:
    """分页元信息(纯函数)。page/page_size 归一到 ≥1;total_pages = ceil(total/page_size)。"""
    page = max(1, int(page))
    page_size = max(1, int(page_size))
    total_pages = math.ceil(total_items / page_size) if total_items else 0
    return {
        "page": page, "page_size": page_size,
        "total_items": total_items, "total_pages": total_pages,
    }


class SessionStore:
    """会话持久化门面。``pg`` = ``pipeline.index.pg_io.PgIO``(``.session()``/``.get()``)。"""

    def __init__(self, pg) -> None:
        self._pg = pg

    def create_conversation(
        self, *, agent_type: str = "institution_query", asker_role: str | None = None,
        title: str | None = None,
    ) -> str:
        cid = str(ULID())
        with self._pg.session() as s:
            s.add(QueryConversation(
                id=cid, agent_type=agent_type, asker_role=asker_role, title=title,
            ))
            s.commit()
        return cid

    def get_conversation(self, cid: str) -> dict | None:
        """会话详情 + 消息列表(不含 result_json,轻量);不存在 → None。"""
        with self._pg.session() as s:
            conv = s.get(QueryConversation, cid)
            if conv is None:
                return None
            msgs = list(s.scalars(
                select(QueryMessage)
                .where(QueryMessage.conversation_id == cid)
                .order_by(QueryMessage.seq)
            ))
            detail = _conv_summary(conv)
            detail["messages"] = [_msg_brief(m) for m in msgs]
            return detail

    def list_conversations(
        self, *, page: int = 1, page_size: int = 20, q: str | None = None,
    ) -> dict:
        """分页 + 标题 ILIKE 搜索,按 updated_at 降序。返回 {data, pagination}。"""
        page = max(1, int(page))
        page_size = max(1, int(page_size))
        with self._pg.session() as s:
            base = select(QueryConversation)
            count_stmt = select(func.count()).select_from(QueryConversation)
            if q:
                like = f"%{q}%"
                base = base.where(QueryConversation.title.ilike(like))
                count_stmt = count_stmt.where(QueryConversation.title.ilike(like))
            total = s.scalar(count_stmt) or 0
            rows = list(s.scalars(
                base.order_by(QueryConversation.updated_at.desc())
                .offset((page - 1) * page_size).limit(page_size)
            ))
            data = [_conv_summary(r) for r in rows]
        return {"data": data, "pagination": paginate(page, page_size, total)}

    def delete_conversation(self, cid: str) -> bool:
        """删会话 + 级联删消息(显式删,不全依赖 DB ondelete)。存在→True。"""
        with self._pg.session() as s:
            conv = s.get(QueryConversation, cid)
            if conv is None:
                return False
            s.execute(delete(QueryMessage).where(QueryMessage.conversation_id == cid))
            s.delete(conv)
            s.commit()
        return True

    def get_message(self, mid: str) -> dict | None:
        """单条消息完整快照(含 result_json,供查看详情/导出);不存在 → None。"""
        with self._pg.session() as s:
            m = s.get(QueryMessage, mid)
            return _msg_full(m) if m is not None else None

    def append_message(
        self, cid: str, *, role: str, content: str | None = None,
        route_type: str | None = None, result_json: dict | None = None,
        hit_counts: dict | None = None, elapsed_ms: int | None = None, ai_label: bool = True,
    ) -> str:
        """追加一轮消息(seq 自增),同步 conversation.message_count / last_hit_counts。

        会话不存在 → ``KeyError``。assistant 消息带 hit_counts 时刷新会话统计卡冗余。
        """
        mid = str(ULID())
        with self._pg.session() as s:
            conv = s.get(QueryConversation, cid)
            if conv is None:
                raise KeyError(cid)
            prior = s.scalar(
                select(func.count()).select_from(QueryMessage)
                .where(QueryMessage.conversation_id == cid)
            ) or 0
            seq = prior + 1
            s.add(QueryMessage(
                id=mid, conversation_id=cid, seq=seq, role=role, content=content,
                route_type=route_type, result_json=result_json, hit_counts=hit_counts,
                elapsed_ms=elapsed_ms, ai_label=ai_label,
            ))
            conv.message_count = seq
            if hit_counts and role == "assistant":
                conv.last_hit_counts = hit_counts
            s.commit()
        return mid


def _conv_summary(conv) -> dict:
    return {
        "id": conv.id, "title": conv.title, "agent_type": conv.agent_type,
        "asker_role": conv.asker_role, "created_at": _iso(conv.created_at),
        "updated_at": _iso(conv.updated_at), "message_count": conv.message_count,
        "last_hit_counts": conv.last_hit_counts,
    }


def _msg_brief(m) -> dict:
    return {
        "id": m.id, "seq": m.seq, "role": m.role, "content": m.content,
        "route_type": m.route_type, "hit_counts": m.hit_counts,
        "ai_label": m.ai_label, "created_at": _iso(m.created_at),
    }


def _msg_full(m) -> dict:
    d = _msg_brief(m)
    d["result_json"] = m.result_json
    d["elapsed_ms"] = m.elapsed_ms
    d["conversation_id"] = m.conversation_id
    return d


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value
