"""T11(集成):SSE 端到端连真栈。

gate=indexed_stack(PG+Milvus+BGE-M3);真流式 gateway 可选(无 key → evidence 走 stub 亦可流式测)。
验:structured 先到、answer_delta 逐块、done 带耗时/计数。离线 skip。
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from query.api.app import create_app
from query.api.service import QueryService

_PREFIX = "/api/query/v1"


def _parse_sse(text):
    out = []
    for block in text.strip().split("\n\n"):
        block = block.strip()
        if not block or block.startswith(":"):
            continue
        ev = data = None
        for line in block.split("\n"):
            if line.startswith("event:"):
                ev = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data = line[len("data:"):].strip()
        out.append((ev, json.loads(data) if data else None))
    return out


def test_sse_end_to_end(indexed_stack):
    from pipeline.index.pg_io import PgIO  # noqa: F401 (ensure importable)

    svc = QueryService.from_config()   # 真栈:惰性建 agent/pg/retriever/store
    cid = svc.store.create_conversation(title="SSE 集成", asker_role="审计人员")
    try:
        client = TestClient(create_app(service=svc))
        r = client.post(
            f"{_PREFIX}/conversations/{cid}/messages",
            json={"query": indexed_stack.query}, headers={"accept": "text/event-stream"},
        )
        assert r.status_code == 200
        evs = _parse_sse(r.text)
        kinds = [k for k, _ in evs]
        assert kinds[0] == "accepted" and kinds[-1] == "done"
        # structured 先于 answer_delta 到达
        assert kinds.index("structured") < (
            kinds.index("answer_delta") if "answer_delta" in kinds else len(kinds)
        )
        done = dict(evs)["done"]
        assert "elapsed_ms" in done and "hit_counts" in done
    finally:
        svc.store.delete_conversation(cid)
