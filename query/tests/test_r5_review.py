"""R5-T2(单元):§9.2 多模型复核接口——toggle 关 passthrough / 开校验降级。零栈零模型。"""

from __future__ import annotations

from types import SimpleNamespace

from query.contract import AnswerBlock, BlockType
from query.judge.review import review_tentative

_CITS = [SimpleNamespace(doc_title="反洗钱管理办法", clause_path="第三条")]
_BLOCKS = [AnswerBlock(BlockType.TEXT, "适用前提:开户推广;适用对象:营业部", stream=False)]


def _llm(supported: bool):
    return SimpleNamespace(chat_json=lambda system, user: {"supported": supported})


def test_review_off_passthrough():
    qcfg = SimpleNamespace(judge_multimodel_review=False)
    out = review_tentative(_BLOCKS, _CITS, llm=_llm(False), qcfg=qcfg)
    assert out == _BLOCKS  # 关 → 原样(不调 LLM、不改块)


def test_review_on_unsupported_downgrades():
    qcfg = SimpleNamespace(judge_multimodel_review=True)
    out = review_tentative(_BLOCKS, _CITS, llm=_llm(False), qcfg=qcfg)
    assert out[0].content != _BLOCKS[0].content  # 不支持 → 降级
    assert "待人工核实" in out[0].content


def test_review_on_supported_keeps():
    qcfg = SimpleNamespace(judge_multimodel_review=True)
    out = review_tentative(_BLOCKS, _CITS, llm=_llm(True), qcfg=qcfg)
    assert out[0].content == _BLOCKS[0].content  # 支持 → 原样


def test_review_malformed_bool_fails_closed():
    # LLM05(Codex 复审):畸形/非严格-bool supported → fail closed(降级),绝不放过
    qcfg = SimpleNamespace(judge_multimodel_review=True)
    for bad in ("false", "true", 1, None, {}):  # 字符串/数字/缺值:均非 bool True → 不支持
        llm = SimpleNamespace(chat_json=lambda s, u, _b=bad: {"supported": _b})
        out = review_tentative(_BLOCKS, _CITS, llm=llm, qcfg=qcfg)
        assert "待人工核实" in out[0].content, bad
    # 完全缺 supported 键 → fail closed
    llm = SimpleNamespace(chat_json=lambda s, u: {})
    assert "待人工核实" in review_tentative(_BLOCKS, _CITS, llm=llm, qcfg=qcfg)[0].content
