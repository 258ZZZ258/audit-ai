"""T5:§9.2 RL-1 真-LLM 忠实性复核闭环(门控集成)。

gate = **QUERY_LLM_BACKEND=gateway + OPENAI_API_KEY**(+ 可选 QUERY_REVIEW_MODEL 指定 Kimi);
缺任一 → **skip(绝不联网)**。聚焦 ``review_tentative`` + 真复核模型(``review_model``,与主答分离),
不走全栈:构造「被所引条款支持 / 不支持」两个文本块,复核开 → 不支持块降「待人工核实」、支持块通过。
证 RL-1 真闭环(非 fake-LLM、非 ``strip_bare_conclusion`` 形态后检)。

运行:
    QUERY_LLM_BACKEND=gateway OPENAI_API_KEY=*** OPENAI_BASE_URL=<gateway> \
      QUERY_REVIEW_MODEL=<kimi 模型名> \
      .venv/bin/python -m pytest query/tests/test_r5_review_integration.py -q
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from query.config import load_query_config
from query.contract import AnswerBlock, BlockType
from query.judge.review import review_tentative
from query.llm import make_llm_client

_PENDING_MARK = "待人工核实"

# 所引条款:仅 doc_title + clause_path 进 prompt(与 review._supported 一致,不含条文正文)。
_CITS = [SimpleNamespace(doc_title="反洗钱管理办法", clause_path="第三条")]
_REVIEW_ON = SimpleNamespace(judge_multimodel_review=True)


@pytest.fixture
def review_llm():
    """真复核客户端(gateway + review_model);未设 gateway/key → skip(绝不联网)。"""
    if os.environ.get("QUERY_LLM_BACKEND") != "gateway" or not os.environ.get("OPENAI_API_KEY"):
        pytest.skip(
            "未设 QUERY_LLM_BACKEND=gateway + OPENAI_API_KEY——RL-1 真-LLM 复核门控跳过(绝不联网)"
        )
    cfg = load_query_config()
    # 复核用 review_model(与主答 llm_model 分离,§9.1)
    return make_llm_client(cfg, model=cfg.review_model)


def test_unsupported_tentative_downgraded(review_llm):
    # 与「反洗钱管理办法」完全无关的表述 → 真复核模型判不支持 → 降「待人工核实」(RL-1 核心)。
    blocks = [AnswerBlock(BlockType.TEXT, "公司年会应当在每年十二月下旬举行。", stream=False)]
    out = review_tentative(blocks, _CITS, review_llm, _REVIEW_ON)
    assert _PENDING_MARK in out[0].content


def test_supported_tentative_kept(review_llm):
    # 与「反洗钱管理办法」主题契合的适用性表述 → 真复核模型判支持 → 原样保留(不误降)。
    text = "适用对象:金融机构;适用前提:开展反洗钱与可疑交易监控相关的内部控制管理。"
    blocks = [AnswerBlock(BlockType.TEXT, text, stream=False)]
    out = review_tentative(blocks, _CITS, review_llm, _REVIEW_ON)
    assert out[0].content == text
