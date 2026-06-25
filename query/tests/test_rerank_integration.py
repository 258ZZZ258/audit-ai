"""§5.5-T4(集成):重排端到端连真栈——rerank=none byte 等价 + bge rerank-hop 真 Milvus text。

gate:PIPELINE_EMBEDDING_MODEL + PG + Milvus(``indexed_stack``)。未满足即 skip。
- `rerank=none`:`with_text=False` → 候选 text 全 None、终态 = RRF 序(等价守护,无需 reranker 模型)。
- `rerank=bge` + **注入 fake reranker**:`with_text=True` → 候选带**真 Milvus text**、reranker 真应用
  (无需本地 reranker 模型即可验承重接线)。
- `rerank=bge` + **真本地 reranker**:需 `QUERY_RERANK_MODEL`,缺则 skip(绝不联网)。
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from query.config import load_query_config
from query.rerank.reranker import BGEReranker
from query.retrieve.hybrid import Retriever


@pytest.fixture(autouse=True)
def _ensure_milvus_connected(indexed_stack):
    """重连 Milvus(幂等):pymilvus 全局别名被 test_r2 模块级 teardown 断开,后跑须重连。"""
    indexed_stack.mio.connect()


def _retriever(indexed_stack, qcfg, reranker=None):
    return Retriever(indexed_stack.ctx.embedding, indexed_stack.mio, qcfg, reranker=reranker)


def test_rerank_none_equivalent_real(indexed_stack):
    qcfg = load_query_config()  # rerank_backend=none(默认)
    out = _retriever(indexed_stack, qcfg).retrieve(indexed_stack.query)
    assert out, "应检索到 ingest 的合同件条款"
    assert all(c.text is None for c in out)  # with_text=False → 无 text 开销
    # 终态 = RRF 分降序(rerank=none passthrough 等价)
    assert [c.score for c in out] == sorted((c.score for c in out), reverse=True)


def test_rerank_bge_hop_real_text(indexed_stack):
    # rerank=bge + 注入反转 fake reranker:候选带真 Milvus text + reranker 真应用(无需本地模型)
    qcfg = load_query_config().model_copy(update={"rerank_backend": "bge"})
    rev = SimpleNamespace(rerank=lambda q, cands: list(reversed(cands)))
    bge_out = _retriever(indexed_stack, qcfg, reranker=rev).retrieve(indexed_stack.query)
    assert bge_out, "应检索到条款"
    assert any(c.text for c in bge_out), "with_text=True → 候选带真 Milvus 截断 text(检索-重排一跳)"
    none_out = _retriever(indexed_stack, load_query_config()).retrieve(indexed_stack.query)
    none_ids = [c.chunk_id for c in none_out]
    bge_ids = [c.chunk_id for c in bge_out]
    assert set(bge_ids) == set(none_ids)        # 同池(本件 pool ≤ topk)
    assert bge_ids == none_ids[::-1]            # fake reranker 反转 → 验证 reranker 真被应用


@pytest.mark.skipif(
    not os.environ.get("QUERY_RERANK_MODEL"),
    reason="未设 QUERY_RERANK_MODEL(本地 bge-reranker-v2-m3);真重排跳过(绝不联网)",
)
def test_rerank_bge_real_model(indexed_stack):
    qcfg = load_query_config().model_copy(update={"rerank_backend": "bge"})
    retr = _retriever(indexed_stack, qcfg, reranker=BGEReranker(qcfg.rerank_model))
    out = retr.retrieve(indexed_stack.query)
    assert out and any(c.text for c in out)     # 真 reranker 跑通,候选带 text
