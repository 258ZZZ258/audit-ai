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
    raw_query = query   # 用户原问:落库存它(F5:history/审计看原问,非内部展开句)
    try:
        # F8:先落 user 原问(在 accepted 之前)——即使随后断连/关流,被 accepted 的问题也不丢
        svc.store.append_message(cid, role="user", content=raw_query)
        yield _sse("accepted", {"conversation_id": cid, "message_id": mid})

        # N0 多轮归并(与 agent.ask 内部一致):route/structured/检索用归并句(多轮 parity,F3)
        query = _merge(svc, raw_query, history)

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
            streamed = False
            for kind, payload in _evidence_stream(svc, query, include_superseded, corpus):
                if kind == "delta":
                    streamed = True
                    yield _sse("answer_delta", {"text": payload})
                else:
                    result = payload
            # F10:result-only(覆盖拒答:充分性闸/无忠实引用,流式前决定)→ 补发答复正文,客户端不空
            if not streamed and result is not None:
                for block in result.answer_blocks:
                    yield _sse("answer_delta", {"text": block.content})
        else:
            # 已归并 → 传空 history 避免 agent 二次归并(F5;query 已自足)
            result = svc.agent.ask(query, history=[])
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
        _append_assistant(svc, cid, result, hit_counts, elapsed_ms, mid)   # user 已落,仅补答复

        yield _sse("done", {
            "message_id": mid, "elapsed_ms": elapsed_ms,
            "total_hits": sum(hit_counts.values()), "hit_counts": hit_counts,
            "ai_label": result.ai_label, "review_required": result.review_required,
            "exhausted_scope": list(result.exhausted_scope),
            "export_enabled": result.export_enabled,
        })
    except Exception:
        # §9 推进可靠性:失败不静默 + 落失败态(user 已落,仅补失败 assistant);best-effort(F6)
        _append_failed(svc, cid, mid)
        yield _sse("error", {"error": {"code": "INTERNAL_ERROR", "message": "生成失败"}})


def _evidence_stream(svc, query, include_superseded, corpus):
    """evidence SSE:**对齐同步 graph._evidence**(One-Version parity,F3/F9)——

    corpus 过滤 → **充分性闸**(``assess(min_hits)`` 不足则覆盖拒答,不流出)→ T10 真流式生成 →
    **案例附挂**(``_maybe_attach_cases`` 同款:开关 + evidence + 非概念判断型)。产出 (delta|result)。
    """
    from query.api.service import _filter_corpus
    from query.case.r3_case import attach_cases
    from query.generate.anchors import fetch_anchors
    from query.generate.r1_evidence import _CLOSEST_N, generate_evidence_stream
    from query.graph import resolve_scope
    from query.refuse.coverage_refusal import refuse_coverage
    from query.retrieve.hybrid import drop_degraded
    from query.retrieve.sufficiency import assess
    from query.understand.classify import SceneType, classify

    cands = _filter_corpus(
        drop_degraded(svc.retriever.retrieve(query, include_superseded=include_superseded)), corpus,
    )
    scene = classify(query)
    scope = resolve_scope(scene.matters)
    # 充分性闸(与同步一致):不足 → 覆盖拒答(附最接近 N 条),绝不流出无覆盖答复
    if not assess(cands, scene.matters, min_hits=svc.qcfg.sufficiency_min_hits).sufficient:
        closest = list(fetch_anchors(svc.pg, [c.chunk_id for c in cands][:_CLOSEST_N]).values())
        yield ("result", refuse_coverage(scope, closest))
        return
    # 充分 → 真流式;delta 照流,终态 result 捕获后再附挂案例
    result = None
    for kind, payload in generate_evidence_stream(
        query, cands, svc.pg, svc.llm, exhausted_scope=scope
    ):
        if kind == "delta":
            yield ("delta", payload)
        else:
            result = payload
    # 案例附挂(与 _maybe_attach_cases 同款:开关 + evidence + 非概念判断型)
    if (result is not None and svc.qcfg.attach_cases
            and result.route_type is RouteType.EVIDENCE
            and scene.scene_type is not SceneType.DEFINITION):
        result = attach_cases(result, query, result.citations, svc.retriever, svc.pg, svc.qcfg)
    yield ("result", result)


def _merge(svc, query, history):
    """N0 归并(F3 parity):有 history 时补全指代/省略为自足问句;llm=None → 规则版兜底。"""
    from query.understand.merge import merge_context

    return merge_context(query, history, llm=getattr(svc, "merge_llm", None))


def _hit_counts(structured) -> dict:
    return {
        "regulations": structured.regulations.count, "clauses": structured.clauses.count,
        "regulatory_rules": structured.regulatory_rules.count, "cases": structured.cases.count,
    }


def _append_failed(svc, cid, mid) -> None:
    """§9:SSE 失败仅补失败态 assistant(user 已在 accepted 前落);best-effort 吞异常(F6/F8)。"""
    try:
        svc.store.append_message(
            cid, role="assistant", content="(生成失败)", route_type="failed",
            ai_label=True, message_id=mid,
        )
    except Exception:
        pass   # 落库失败不掩盖原 error 事件


def _append_assistant(svc, cid, result, hit_counts, elapsed_ms, mid) -> None:
    """仅补 assistant(user 已在 accepted 前落,F8)。用**广告的 mid** → GET/导出可回查(F2)。"""
    svc.store.append_message(
        cid, role="assistant", content="".join(b.content for b in result.answer_blocks),
        route_type=result.route_type.value, result_json=result.to_dict(),
        hit_counts=hit_counts, elapsed_ms=elapsed_ms, ai_label=result.ai_label, message_id=mid,
    )
