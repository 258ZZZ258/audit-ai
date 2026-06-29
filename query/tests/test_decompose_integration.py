"""T5:N3 问题分解真-LLM 闭环(门控集成)。

gate = gateway + OPENAI_API_KEY(+ 可选 QUERY_DECOMPOSE_MODEL);缺任一 → skip(绝不联网)。聚焦
``decompose_subqueries`` + 真分解模型:复合问句拆 >1 子查询、单跳问句返单个。不走全栈。本地无 key →
skip(诚实记 🟡,待真 gateway 跑绿翻 ✅);复合占比/拆分质量由 §13 V0 实测,非本测范围。

运行:
    QUERY_LLM_BACKEND=gateway OPENAI_API_KEY=*** OPENAI_BASE_URL=<gateway> \
      QUERY_DECOMPOSE_MODEL=<分解模型名> \
      .venv/bin/python -m pytest query/tests/test_decompose_integration.py -q
"""

from __future__ import annotations

import os

import pytest

from query.config import load_query_config
from query.llm import make_llm_client
from query.retrieve.decompose import decompose_subqueries


@pytest.fixture
def decompose_llm():
    """真分解客户端(gateway + decompose_model);未设 gateway/key → skip(绝不联网)。"""
    if os.environ.get("QUERY_LLM_BACKEND") != "gateway" or not os.environ.get("OPENAI_API_KEY"):
        pytest.skip(
            "未设 QUERY_LLM_BACKEND=gateway + OPENAI_API_KEY——N3 真-LLM 分解门控跳过(绝不联网)"
        )
    cfg = load_query_config()
    return make_llm_client(cfg, model=cfg.decompose_model or cfg.llm_model)


def test_compound_query_decomposed(decompose_llm):
    # 显式复合问句(两个子约束)→ 真 LLM 拆 >1 子查询。
    subs = decompose_subqueries("私募权益投顾同时管偏股和偏债是否违规", decompose_llm)
    assert len(subs) > 1  # 复合 → fan-out


def test_single_query_passthrough(decompose_llm):
    # 单跳问句 → 真 LLM 返单个 → 原问直通(单查询)。
    q = "费用报销发票需要保存几个月"
    assert decompose_subqueries(q, decompose_llm) == [q]
