"""T5(SPEC-API §3/§7):会话端点。

``POST /conversations``(新会话)· ``GET /conversations``(分页 + 标题搜索)·
``GET /conversations/{cid}``(详情:元信息 + 系统摘要 + 统计卡 + 消息)· ``DELETE`` 删会话。
薄壳:只经 ``SessionStore``;asker_role 取自鉴权主体(stub)。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from query.api.auth import Principal, current_principal
from query.api.errors import not_found
from query.api.service import QueryService, get_service

router = APIRouter(prefix="/conversations", tags=["conversations"])


class CreateConversationBody(BaseModel):
    agent_type: str = "institution_query"
    title: str | None = None


@router.post("", status_code=201)
def create_conversation(
    body: CreateConversationBody | None = None,
    svc: QueryService = Depends(get_service),
    principal: Principal = Depends(current_principal),
) -> dict:
    body = body or CreateConversationBody()
    cid = svc.store.create_conversation(
        agent_type=body.agent_type, asker_role=principal.role, title=body.title,
    )
    return {"id": cid, "agent_type": body.agent_type, "title": body.title}


@router.get("")
def list_conversations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),   # >100 → 422(统一错误体)
    q: str | None = Query(None, description="按会话标题搜索"),
    svc: QueryService = Depends(get_service),
) -> dict:
    return svc.store.list_conversations(page=page, page_size=page_size, q=q)


@router.get("/{cid}")
def get_conversation(cid: str, svc: QueryService = Depends(get_service)) -> dict:
    detail = svc.store.get_conversation(cid)
    if detail is None:
        raise not_found("会话不存在")
    return _detail_response(detail)


@router.delete("/{cid}")
def delete_conversation(cid: str, svc: QueryService = Depends(get_service)) -> dict:
    if not svc.store.delete_conversation(cid):
        raise not_found("会话不存在")
    return {"deleted": True}


def _detail_response(detail: dict) -> dict:
    """派生 SPEC §7.2 详情:用户问题(首个 user)+ 系统摘要(最近 assistant)+ 统计卡。"""
    msgs = detail.get("messages", [])
    user_q = next((m["content"] for m in msgs if m["role"] == "user"), None)
    summary = next((m["content"] for m in reversed(msgs) if m["role"] == "assistant"), None)
    return {
        "id": detail["id"], "title": detail["title"], "agent_type": detail["agent_type"],
        "asker_role": detail["asker_role"], "created_at": detail["created_at"],
        "user_question": user_q, "summary": summary,
        "hit_counts": detail.get("last_hit_counts"),   # 四张统计卡
        "messages": msgs,
    }
