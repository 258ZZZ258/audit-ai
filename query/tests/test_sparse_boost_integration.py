"""§5.4-T4(集成):查询层 sparse 精确增强端到端连真栈。

gate:PIPELINE_EMBEDDING_MODEL + PG + Milvus(``sparse_stack``)。未满足即 skip。
- 发文字号提权:查询含发文字号 + 语义「合同管理」→ `docnum_boost=True` 时含发文字号条款名次升或持平
  (加权并入发文字号 token 只增不降其 sparse 秩)。
- 词典扩展:口语查「代客理财」→ `scenario_expand=True` 召回含法言词「受托理财」的条款,名次升或持平。
- 双关关:默认 retrieve 真栈正常返回(off-path 不受影响)。
断言取「名次升或持平」(加权不降目标秩,稳健);严格名次跃升属 §15 V0 标定。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from common.pg_models import Chunk
from query.config import QueryConfig
from query.retrieve.hybrid import Retriever


@pytest.fixture(autouse=True)
def _reconnect(sparse_stack):
    """重连 Milvus(幂等):pymilvus 全局别名可能被其他模块 teardown 断开。"""
    sparse_stack.mio.connect()


def _retr(stack, **cfg):
    return Retriever(stack.ctx.embedding, stack.mio, QueryConfig(**cfg))


def _leaf_chunk_with(pg, dvid, needle):
    """该件中文本含 needle 的叶子(Milvus 索引)chunk_id;父块(节级,仅 PG)排除。"""
    with pg.session() as s:
        return s.scalar(
            select(Chunk.chunk_id).where(
                Chunk.doc_version_id == dvid,
                Chunk.is_parent.is_(False),
                Chunk.text.contains(needle),
            )
        )


def _rank(out, cid):
    ids = [c.chunk_id for c in out]
    return ids.index(cid) if cid in ids else len(ids) + 1


def test_docnum_boost_recall_no_regression(sparse_stack):
    """§5.1 hybrid 小语料已把发文字号精确命中置顶(off_rank=0)→ 端到端验:提权下目标仍召回、不回归。
    "严格抬升名次"是大语料 / §15 V0 性质;机制非无效由单元 sparse-IP 测证。
    """
    target = _leaf_chunk_with(sparse_stack.pg, sparse_stack.dvid, "银保监发")
    assert target, "未找到含发文字号的叶子 chunk"
    q = sparse_stack.docnum_query
    off = _retr(sparse_stack).retrieve(q)  # docnum_boost 默认关
    on = _retr(sparse_stack, docnum_boost=True).retrieve(q)
    assert target in [c.chunk_id for c in on]  # 端到端召回
    assert _rank(on, target) <= _rank(off, target)  # 提权不回归(只增不降目标 sparse 秩)


def test_scenario_expand_recall_no_regression(sparse_stack, tmp_path):
    """词典扩展端到端:口语 jargon 经 dict 映射注入法言词 → 召回目标条款、不回归。
    "严格抬升"受限于小语料 dense 桥接(同 docnum);机制非无效由单元 sparse-IP 测证。
    """
    # jargon「见底到顶」→ 法言「买卖时机|具体建议」(目标条款只含法言词,不含 jargon)
    csv_path = tmp_path / "scn.csv"
    csv_path.write_text("oral_term,legal_terms\n见底到顶,买卖时机|具体建议\n", encoding="utf-8")
    target = _leaf_chunk_with(sparse_stack.pg, sparse_stack.dvid, "买卖时机")
    assert target, "未找到含法言词的叶子 chunk"
    q = sparse_stack.oral_query  # "见底到顶这类提法可以吗"
    off = _retr(sparse_stack).retrieve(q)  # scenario_expand 关
    on = _retr(
        sparse_stack, scenario_expand=True, scenario_terms_path=str(csv_path)
    ).retrieve(q)
    assert target in [c.chunk_id for c in on]  # 扩展 → 召回法言条款(端到端)
    assert _rank(on, target) <= _rank(off, target)  # 不回归


def test_sparse_both_off_smoke(sparse_stack):
    out = _retr(sparse_stack).retrieve(sparse_stack.docnum_query)
    assert out  # 双关默认关:off-path 真栈正常返回(不回归)
