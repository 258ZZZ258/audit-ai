"""T5:N1 HyDE 真-LLM 生成闭环(门控集成)。

gate = **QUERY_LLM_BACKEND=gateway + OPENAI_API_KEY**(+ 可选 QUERY_HYDE_MODEL 指定 HyDE 模型);
缺任一 → **skip(绝不联网)**。聚焦 ``hyde_dense_text`` + 真 HyDE 模型:口语问句 → 非空假设性法言,
与原问拼接为 dense 检索文本。不走全栈/Milvus。本地无 key → skip(诚实记 🟡,待真 gateway 跑绿翻 ✅)。
**召回收益**(hit@10)由 §13 V0 第5组 A/B 实测,非本测范围(本测只证生成闭环)。

运行:
    QUERY_LLM_BACKEND=gateway OPENAI_API_KEY=*** OPENAI_BASE_URL=<gateway> \
      QUERY_HYDE_MODEL=<HyDE 模型名> \
      .venv/bin/python -m pytest query/tests/test_hyde_integration.py -q
"""

from __future__ import annotations

import os

import pytest

from query.config import load_query_config
from query.llm import make_llm_client
from query.retrieve.hyde import hyde_dense_text


@pytest.fixture
def hyde_llm():
    """真 HyDE 客户端(gateway + hyde_model);未设 gateway/key → skip(绝不联网)。"""
    if os.environ.get("QUERY_LLM_BACKEND") != "gateway" or not os.environ.get("OPENAI_API_KEY"):
        pytest.skip(
            "未设 QUERY_LLM_BACKEND=gateway + OPENAI_API_KEY——N1 真-LLM HyDE 门控跳过(绝不联网)"
        )
    cfg = load_query_config()
    return make_llm_client(cfg, model=cfg.hyde_model or cfg.llm_model)


def test_hyde_generates_passage(hyde_llm):
    # 口语问句 → 真 LLM 写出假设性法言条款,与原问拼接为 dense 检索文本(非空、含原问)。
    query = "二维码介绍开户违不违规"
    out = hyde_dense_text(query, hyde_llm)
    assert out is not None                # 生成成功(非 fail-safe None)
    assert out.startswith(query)          # 原问在前(§3.1 一同送入 dense)
    assert len(out) > len(query) + 5      # 拼接了一段法言(非空 passage)
