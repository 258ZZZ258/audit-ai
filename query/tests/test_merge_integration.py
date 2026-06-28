"""T6:N0 多轮归并真-LLM 闭环(门控集成)。

gate = **QUERY_LLM_BACKEND=gateway + OPENAI_API_KEY**(+ 可选 QUERY_MERGE_MODEL 指定归并模型);
缺任一 → **skip(绝不联网)**。聚焦 ``merge_context`` + 真归并模型(``merge_model``,None→复用主答),
不走全栈:多轮指代/省略 → 真 LLM 消解为自足问句(含上轮主题、不含裸指代);R7 澄清答归并回原问。
本地无 key → skip(诚实记 🟡,待真 gateway 跑绿翻 ✅)。

运行:
    QUERY_LLM_BACKEND=gateway OPENAI_API_KEY=*** OPENAI_BASE_URL=<gateway> \
      QUERY_MERGE_MODEL=<归并模型名> \
      .venv/bin/python -m pytest query/tests/test_merge_integration.py -q
"""

from __future__ import annotations

import os

import pytest

from query.config import load_query_config
from query.llm import make_llm_client
from query.understand.merge import merge_context


@pytest.fixture
def merge_llm():
    """真归并客户端(gateway + merge_model);未设 gateway/key → skip(绝不联网)。"""
    if os.environ.get("QUERY_LLM_BACKEND") != "gateway" or not os.environ.get("OPENAI_API_KEY"):
        pytest.skip(
            "未设 QUERY_LLM_BACKEND=gateway + OPENAI_API_KEY——N0 真-LLM 归并门控跳过(绝不联网)"
        )
    cfg = load_query_config()
    return make_llm_client(cfg, model=cfg.merge_model or cfg.llm_model)


def test_llm_resolves_coreference(merge_llm):
    # 多轮指代:上轮主题=私募基金管理人,当前"它"→真 LLM 消解为自足问句(含主题、去裸指代)。
    history = [
        {"role": "user", "content": "私募基金管理人的登记要求是什么"},
        {"role": "assistant", "content": "根据相关规定,需向基金业协会登记……"},
    ]
    merged = merge_context("它需要多少实缴资本", history, llm=merge_llm)
    assert merged != "它需要多少实缴资本"          # 已归并(非原样)
    assert "私募" in merged                          # 上轮主题被补全进问句


def test_llm_r7_clarify_closure(merge_llm):
    # R7 澄清闭环:原问 + 澄清答 → 真 LLM 归并为自足问句(保留原问主题 + 澄清约束)。
    history = [
        {"role": "user", "content": "合同管理办法什么时候修订的"},
        {"role": "assistant", "content": "您问现行版本还是某历史版本?", "route_type": "clarify"},
    ]
    merged = merge_context("现行版本", history, llm=merge_llm)
    assert "合同管理办法" in merged                 # 原问主题保留
    assert "现行" in merged                          # 澄清约束并入
