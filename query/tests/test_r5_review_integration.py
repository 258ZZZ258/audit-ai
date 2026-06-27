"""T5:§9.2 RL-1 真-LLM 忠实性复核闭环(门控集成)。

gate = **QUERY_LLM_BACKEND=gateway + OPENAI_API_KEY**(+ 可选 QUERY_REVIEW_MODEL 指定 Kimi);
缺任一 → **skip(绝不联网)**。聚焦 ``review_tentative`` + 真复核模型(``review_model``,与主答分离),
不走全栈:喂**所引条款原文**(R5-REVIEW-NEEDS-CLAUSE-EVIDENCE),构造「被条文支持 / 不被支持」两块,
复核开 → 不支持块降「待人工核实」、支持块通过。证 RL-1 真闭环(基于条文证据,非 fake/形态后检)。

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

# 所引条款**含正文**(与 review._supported 一致:题名 + 条号 + 条文原文 → 复核 prompt)。
# 同一题名/条号、条文是反洗钱大额/可疑交易报告——据此真模型可判表述是否被条文支持。
_CLAUSES = [
    {
        "doc_title": "反洗钱管理办法",
        "clause_path": "第三条",
        "text": "金融机构应当对大额交易和可疑交易进行报告,并建立健全反洗钱内部控制制度。",
    }
]
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


def test_unsupported_by_clause_text_downgraded(review_llm):
    # 同一条款(反洗钱第三条)但其条文**不涉及**该表述(上市公司关联交易披露)→ 真复核模型据**条文原文**
    # 判不支持 → 降「待人工核实」(RL-1 核心:基于证据、非题名 plausibility)。
    stmt = "上市公司董事应当在三个交易日内披露其关联交易事项。"
    blocks = [AnswerBlock(BlockType.TEXT, stmt, stream=False)]
    out = review_tentative(blocks, _CLAUSES, review_llm, _REVIEW_ON)
    assert _PENDING_MARK in out[0].content


def test_supported_by_clause_text_kept(review_llm):
    # 表述与条文原文契合(金融机构对可疑交易报告 + 反洗钱内控)→ 真复核模型判支持 → 原样保留。
    text = "适用对象:金融机构;适用前提:对可疑交易进行报告并建立健全反洗钱内部控制。"
    blocks = [AnswerBlock(BlockType.TEXT, text, stream=False)]
    out = review_tentative(blocks, _CLAUSES, review_llm, _REVIEW_ON)
    assert out[0].content == text
