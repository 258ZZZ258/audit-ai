"""R5-T1(单元):不出裸结论后检 + 三段式构成要件框定。零栈零模型。

红线核心:strip_bare_conclusion(verdict + 试探性 → 中性);三段式无 verdict 槽(②框定 + ③标识)。
"""

from __future__ import annotations

from types import SimpleNamespace

from query.config import load_query_config
from query.contract import BlockType
from query.judge.framing import build_framing, strip_bare_conclusion

_CLAUSES = [
    {"doc_title": "反洗钱管理办法", "clause_path": "第三条", "text": "客户身份识别相关规定。"},
    {"doc_title": "账户管理细则", "clause_path": "第五条", "text": "账户开立审查相关规定。"},
]
_VERDICT_WORDS = ("违规", "违法", "合规", "合法", "可能违反", "疑似违规", "涉嫌", "倾向于不合规")


def test_strip_verdict_words():
    for bad in ("该行为违规", "属于合规操作", "构成违法", "完全合法"):
        assert strip_bare_conclusion(bad) != bad
        assert not any(w in strip_bare_conclusion(bad) for w in ("违规", "违法", "合规", "合法"))


def test_strip_tentative_phrasing():
    # §9.2 试探性表述同样降中性(可能违反/疑似违规/涉嫌/倾向于不合规)
    for bad in ("可能违反第三条", "疑似违规", "涉嫌违反规定", "倾向于不合规"):
        assert strip_bare_conclusion(bad) != bad


def test_strip_keeps_neutral_text():
    good = "相关依据见所引条款原文,适用前提/对象/行为类型见条款。"
    assert strip_bare_conclusion(good) == good


def test_build_framing_default_clause_passthrough():
    qcfg = SimpleNamespace(judge_constituent_llm=False)
    blocks = build_framing(_CLAUSES, "二维码介绍开户是否违规", llm=None, qcfg=qcfg)
    assert len(blocks) == 2
    assert all(b.type is BlockType.TEXT for b in blocks)
    # ② 框定:clause直呈(含命中条款引用),零 LLM
    assert "反洗钱管理办法" in blocks[0].content and "第三条" in blocks[0].content
    # ③ AI 辅助/人工复核标识
    assert "人工复核" in blocks[1].content
    # 红线:任一块都不含 verdict/试探性裸结论(无 verdict 槽 + 安全文案避词)
    for b in blocks:
        assert not any(w in b.content for w in _VERDICT_WORDS)


def test_build_framing_llm_toggle_stripped():
    # judge_constituent_llm 开 + LLM 返带裸结论的框定 → strip 守红线
    qcfg = SimpleNamespace(judge_constituent_llm=True)
    fake_llm = SimpleNamespace(
        chat_json=lambda system, user: {"framing": "适用前提:开户推广;本问句可能违反第三条规定"}
    )
    blocks = build_framing(_CLAUSES, "二维码介绍开户是否违规", llm=fake_llm, qcfg=qcfg)
    assert not any(w in blocks[0].content for w in _VERDICT_WORDS)  # 试探性被剥离


def test_no_verdict_slot_structurally():
    # 三段式 = answer_blocks(TEXT),无"判定/verdict"字段(AnswerBlock 只 type/content/stream)
    qcfg = SimpleNamespace(judge_constituent_llm=False)
    blocks = build_framing(_CLAUSES, "x", llm=None, qcfg=qcfg)
    assert all(set(vars(b)) == {"type", "content", "stream"} for b in blocks)


def test_config_toggles_default_off():
    cfg = load_query_config()
    assert cfg.judge_constituent_llm is False
    assert cfg.judge_multimodel_review is False
