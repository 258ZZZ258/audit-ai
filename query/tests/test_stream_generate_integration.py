"""T10(集成):真 gateway token 流式(§7.2)。

gate=indexed_stack + QUERY_LLM_BACKEND=gateway + OPENAI_API_KEY;缺任一 skip(离线不联网)。
验:充分路径先收到 delta 再收 result,引用非空(真流式端到端)。
"""

from __future__ import annotations

import os

import pytest


def test_stream_generate_gateway(indexed_stack):
    if os.environ.get("QUERY_LLM_BACKEND") != "gateway" or not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("需 QUERY_LLM_BACKEND=gateway + OPENAI_API_KEY(真流式门控)")

    from query.config import load_query_config
    from query.generate.r1_evidence import generate_evidence_stream
    from query.llm import make_llm_client
    from query.retrieve.hybrid import Retriever, drop_degraded

    pg, mio, ctx, _dvid, query = indexed_stack
    qcfg = load_query_config()
    cands = drop_degraded(Retriever(ctx.embedding, mio, qcfg).retrieve(query))
    events = list(generate_evidence_stream(query, cands, pg, make_llm_client(qcfg)))

    assert events and events[-1][0] == "result"
    result = events[-1][1]
    if result.route_type.value == "evidence":   # 充分路径:真流式验证
        assert any(k == "delta" for k, _ in events)
        assert result.citations
