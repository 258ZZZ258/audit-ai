"""T6(SPEC-API §6):问答端点(同步 JSON)。

``POST /conversations/{cid}/messages``(同步 JSON):校验 query≤2000 / 附件 / corpus → 取会话 history →
``agent.ask`` → ``structured_for`` 装配四-Tab → 落 user+assistant → 返 §10+structured。
中途异常不静默(经统一 500,不写半截)。SSE 分支(text/event-stream)在 T11 加。
"""

from __future__ import annotations

import time
from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from query.api.errors import not_found, validation_error
from query.api.service import QueryService, get_service

router = APIRouter(prefix="/conversations", tags=["messages"])


class AskBody(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)   # >2000 → 422
    attachments: list[str] = []
    include_superseded: bool = False
    corpus: Literal["internal", "external"] | None = None


@router.post("/{cid}/messages")
def ask(cid: str, body: AskBody, request: Request, svc: QueryService = Depends(get_service)):
    conv = svc.store.get_conversation(cid)
    if conv is None:
        raise not_found("会话不存在")
    _validate_attachments(svc, body.attachments)

    history = [
        {"role": m["role"], "content": m["content"]}
        for m in conv.get("messages", []) if m.get("content")
    ]

    # SSE 分支(Accept: text/event-stream);否则同步 JSON
    if "text/event-stream" in request.headers.get("accept", ""):
        from query.api.sse import stream_ask

        return StreamingResponse(
            stream_ask(
                svc, cid, body.query, history,
                include_superseded=body.include_superseded, corpus=body.corpus,
            ),
            media_type="text/event-stream",
        )

    t0 = time.perf_counter()
    result = svc.agent.ask(body.query, history=history)   # 异常 → 统一 500(非静默,不落半截)
    result.structured = svc.structured_for(
        body.query, include_superseded=body.include_superseded, corpus=body.corpus,
    )
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    hit_counts = _hit_counts(result.structured)
    result.meta = {
        "elapsed_ms": elapsed_ms, "total_hits": sum(hit_counts.values()), "hit_counts": hit_counts,
    }
    _persist(svc, cid, body.query, result, hit_counts, elapsed_ms)
    return result.to_dict()


def _validate_attachments(svc: QueryService, attachments: list[str]) -> None:
    """附件须引用已上传的 upload_id(uploads 注册表在 T8 落地;缺失 → 422)。"""
    uploads = getattr(svc, "uploads", {})
    missing = [a for a in attachments if a not in uploads]
    if missing:
        raise validation_error("附件不存在或已过期", {"missing": missing})


def _hit_counts(structured) -> dict:
    return {
        "regulations": structured.regulations.count, "clauses": structured.clauses.count,
        "regulatory_rules": structured.regulatory_rules.count, "cases": structured.cases.count,
    }


def _persist(svc, cid, query, result, hit_counts, elapsed_ms) -> None:
    """落 user + assistant(在结果算出后,失败则不留半截)。assistant 存契约快照供历史/导出。"""
    svc.store.append_message(cid, role="user", content=query)
    svc.store.append_message(
        cid, role="assistant", content=_answer_text(result),
        route_type=result.route_type.value, result_json=result.to_dict(),
        hit_counts=hit_counts, elapsed_ms=elapsed_ms, ai_label=result.ai_label,
    )


def _answer_text(result) -> str:
    return "".join(b.content for b in result.answer_blocks)
