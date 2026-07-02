"""audit-biz -> audit-ai 边界二:无状态 ``POST /v1/query`` SSE 薄壳。

本 router 独立于前端向 ``/api/query/v1/*`` 会话式 API:无用户身份、无会话落库、无导出、
无 PG 引用回查;只消费 Java 预计算的过滤位并把 ``QueryResult`` 映射为边界五事件。
"""

from __future__ import annotations

import json
import os
from contextlib import nullcontext
from typing import Literal

from fastapi import APIRouter, Depends, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from query.api.errors import ApiError, validation_error
from query.api.service import QueryService, get_service
from query.contract import QueryResult, RouteType
from query.retrieve.hybrid import Candidate

router = APIRouter(tags=["boundary"])

_CORPUS_MAP = {
    "internal": "P-INT",
    "external": "P-EXT",
    "qa": "P-QA",
    "case": "P-CASE",
    "audit_project": "audit_project",
}


class BoundaryFilters(BaseModel):
    perm_tags: list[str]
    corpus_types: list[Literal["internal", "external", "qa", "case", "audit_project"]]
    project_id: str | None = None
    owner: str | None = None


class BoundaryOptions(BaseModel):
    top_k: int | None = Field(default=None, ge=1)
    include_superseded: bool = False


class BoundaryQueryRequest(BaseModel):
    query: str = Field(..., min_length=1)
    request_id: str = Field(..., min_length=1)
    filters: BoundaryFilters
    options: BoundaryOptions = Field(default_factory=BoundaryOptions)


def require_internal_token(x_internal_token: str | None = Header(default=None)) -> None:
    expected = os.environ.get("AUDIT_AI_INTERNAL_TOKEN")
    if not expected or x_internal_token != expected:
        raise ApiError(401, "B104", "内部令牌无效")


@router.post("/v1/query")
def query_boundary(
    body: BoundaryQueryRequest,
    _auth: None = Depends(require_internal_token),
    svc: QueryService = Depends(get_service),
):
    scope = _build_scope(body.filters, body.options)
    return StreamingResponse(
        _stream_query(svc, body, scope),
        media_type="text/event-stream",
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _stream_query(svc, body: BoundaryQueryRequest, scope: dict):
    try:
        with _scoped_retriever(svc, scope):
            result = _ask(svc, body)
            score_map = _score_map(
                svc, body.query, include_superseded=body.options.include_superseded
            )

        yield _sse("meta", {
            "request_id": body.request_id,
            "route_type": result.route_type.value,
            "ai_label": result.ai_label,
            "review_required": result.review_required,
            "export_enabled": result.export_enabled,
        })
        for seq, block in enumerate(result.answer_blocks):
            yield _sse("delta", {
                "block_seq": seq,
                "block_type": block.type.value,
                "text": block.content,
            })
        for citation in result.citations:
            yield _sse("citation", {
                "clause_id": citation.clause_id,
                "chunk_id": citation.clause_id,
                "score": score_map.get(citation.clause_id),
            })
        yield _sse("done", {
            "finish_reason": "refused" if result.route_type is RouteType.REFUSE else "stop",
            "confidence": result.confidence,
            "exhausted_scope": list(result.exhausted_scope),
        })
    except Exception:
        yield _sse("error", {"code": "INTERNAL_ERROR", "message": "生成失败"})


def _ask(svc, body: BoundaryQueryRequest) -> QueryResult:
    try:
        return svc.agent.ask(body.query, trace_id=body.request_id)
    except TypeError:
        # 测试桩可能还没有 trace_id 形参;生产 QueryAgent 支持该参数。
        return svc.agent.ask(body.query)


def _build_scope(filters: BoundaryFilters, options: BoundaryOptions) -> dict:
    corpus = tuple(_CORPUS_MAP[c] for c in filters.corpus_types)
    exprs: list[str] = []
    if filters.perm_tags:
        exprs.append(f"array_contains_any(perm_tag, {_json_array(filters.perm_tags)})")

    # 当前 audit-ai v1.6 Milvus schema 尚无 project_id/owner 字段。制度语料按契约忽略 owner;
    # audit_project 带 project_id/owner 时若静默放宽会破隔离,因此先拒绝而非检索后过滤。
    if "audit_project" in filters.corpus_types and (filters.project_id or filters.owner):
        raise validation_error(
            "audit_project 的 project_id/owner 前置过滤当前未接入 Milvus schema",
            {"corpus_types": filters.corpus_types},
        )

    return {
        "corpora": corpus,
        "extra_expr": " and ".join(exprs) if exprs else None,
        "topk": options.top_k,
        "partition_topk": options.top_k,
    }


def _json_array(values: list[str]) -> str:
    return json.dumps(values, ensure_ascii=False)


def _scoped_retriever(svc, scope: dict):
    retriever = getattr(svc, "retriever", None)
    scoped = getattr(retriever, "scoped", None)
    if scoped is None:
        return nullcontext()
    return scoped(**scope)


def _score_map(svc, query: str, *, include_superseded: bool) -> dict[str, float]:
    candidates: list[Candidate] = []
    retriever = getattr(svc, "retriever", None)
    if retriever is None:
        return {}
    for method in ("retrieve", "retrieve_cases"):
        fn = getattr(retriever, method, None)
        if fn is None:
            continue
        try:
            candidates.extend(fn(query, include_superseded=include_superseded))
        except Exception:
            continue
    return _normalise_scores(candidates)


def _normalise_scores(candidates: list[Candidate]) -> dict[str, float]:
    by_id: dict[str, float] = {}
    for c in candidates:
        prev = by_id.get(c.chunk_id)
        if prev is None or c.score > prev:
            by_id[c.chunk_id] = c.score
    if not by_id:
        return {}
    lo = min(by_id.values())
    hi = max(by_id.values())
    if hi == lo:
        return {k: 1.0 for k in by_id}
    return {k: (v - lo) / (hi - lo) for k, v in by_id.items()}
