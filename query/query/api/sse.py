"""T11(SPEC-API §6.2):SSE 事件编排。

事件序列:``accepted`` → ``route`` → ``structured``(四-Tab 一次)→ ``answer_delta``*(真流式喂)→
``citations`` → ``done``;任一阶段异常 → ``error``。evidence 路由走 T10 ``generate_evidence_stream``
真流式;其余路由用 ``agent.ask`` 全量结果、答复块作 delta 交付。落库同同步路径。

复用 graph 域逻辑(classify/resolve_scope/retrieve/generate_evidence_stream)——流式路径与 graph
非流式路径并存(PLAN 接受);不改 graph 节点。
"""

from __future__ import annotations

import json
import time

from query.contract import RouteType

_KEEPALIVE = ": keep-alive\n\n"   # 注释帧(空闲防代理断连;编排层按需插)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def stream_ask(svc, cid, query, history, *, include_superseded=False, corpus=None):
    """SSE 生成器:yield 一串 ``event:/data:`` 帧。异常兜底为 ``error`` 事件(不静默)。"""
    from ulid import ULID

    mid = str(ULID())
    try:
        yield _sse("accepted", {"conversation_id": cid, "message_id": mid})

        route = svc.agent.route_only(query)
        yield _sse("route", {
            "route_type": route.value, "review_required": route is RouteType.JUDGMENTAL,
        })

        structured = svc.structured_for(
            query, include_superseded=include_superseded, corpus=corpus,
        )
        yield _sse("structured", structured.to_dict())

        t0 = time.perf_counter()
        if route is RouteType.EVIDENCE:
            result = None
            for kind, payload in _evidence_stream(svc, query, include_superseded):
                if kind == "delta":
                    yield _sse("answer_delta", {"text": payload})
                else:
                    result = payload
        else:
            result = svc.agent.ask(query, history=history)
            for block in result.answer_blocks:
                yield _sse("answer_delta", {"text": block.content})
        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        yield _sse("citations", {"citations": [c.to_dict() for c in result.citations]})

        result.structured = structured
        hit_counts = _hit_counts(structured)
        result.meta = {
            "elapsed_ms": elapsed_ms, "total_hits": sum(hit_counts.values()),
            "hit_counts": hit_counts,
        }
        _persist(svc, cid, query, result, hit_counts, elapsed_ms)

        yield _sse("done", {
            "message_id": mid, "elapsed_ms": elapsed_ms,
            "total_hits": sum(hit_counts.values()), "hit_counts": hit_counts,
            "ai_label": result.ai_label, "review_required": result.review_required,
            "exhausted_scope": list(result.exhausted_scope),
            "export_enabled": result.export_enabled,
        })
    except Exception:
        yield _sse("error", {"error": {"code": "INTERNAL_ERROR", "message": "生成失败"}})


def _evidence_stream(svc, query, include_superseded):
    """evidence 路由:检索 + T10 真流式生成(yield (delta|result, payload))。"""
    from query.generate.r1_evidence import generate_evidence_stream
    from query.graph import resolve_scope
    from query.retrieve.hybrid import drop_degraded
    from query.understand.classify import classify

    cands = drop_degraded(svc.retriever.retrieve(query, include_superseded=include_superseded))
    scope = resolve_scope(classify(query).matters)
    yield from generate_evidence_stream(query, cands, svc.pg, svc.llm, exhausted_scope=scope)


def _hit_counts(structured) -> dict:
    return {
        "regulations": structured.regulations.count, "clauses": structured.clauses.count,
        "regulatory_rules": structured.regulatory_rules.count, "cases": structured.cases.count,
    }


def _persist(svc, cid, query, result, hit_counts, elapsed_ms) -> None:
    svc.store.append_message(cid, role="user", content=query)
    svc.store.append_message(
        cid, role="assistant", content="".join(b.content for b in result.answer_blocks),
        route_type=result.route_type.value, result_json=result.to_dict(),
        hit_counts=hit_counts, elapsed_ms=elapsed_ms, ai_label=result.ai_label,
    )
