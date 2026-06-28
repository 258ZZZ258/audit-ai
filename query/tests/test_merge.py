"""T2(单元,零栈零网络):N0 多轮归并 merge.py —— 规则版核 + LLM 接缝 + fail-safe。

覆盖 SC1(R7 闭环)/SC2(代词顺承)/SC3(no-op)/SC4(LLM 为主+fail-safe)/坏轮忽略 + parse 畸形。
规则版确定性、绝不阻断、绝不臆造引用(只改写问句)。深度指代消解归 gateway 真 LLM(见集成测)。
"""

from __future__ import annotations

from query.understand.merge import (
    MERGE_SYSTEM,
    build_merge_user,
    merge_context,
    parse_merged,
)


class _FakeLLM:
    """LLMClient 桩:返回固定 resp,或 raises=True 抛(验 fail-safe)。"""

    def __init__(self, resp: dict | None = None, *, raises: bool = False) -> None:
        self._resp = resp
        self._raises = raises
        self.calls = 0

    def chat_json(self, system: str, user: str) -> dict:
        self.calls += 1
        if self._raises:
            raise RuntimeError("gateway boom")
        return self._resp or {}


_CLARIFY_HIST = [
    {"role": "user", "content": "合同管理办法什么时候改的"},
    {"role": "assistant", "content": "您问现行版本还是某历史版本?", "route_type": "clarify"},
]
_ANSWER_HIST = [
    {"role": "user", "content": "内幕交易的认定标准"},
    {"role": "assistant", "content": "根据相关规定……(略)"},
]


# ── SC3:单轮 no-op(空 history → 原句,byte 等价)────────────────────────────
def test_merge_noop_empty_history():
    assert merge_context("费用报销三个月的规定在哪", []) == "费用报销三个月的规定在哪"


def test_merge_noop_no_llm_no_rule():
    # 有 history 但当前问句自足(无指代、不短)→ 规则版返 None → 原句
    q = "洗钱罪的构成要件是什么"
    assert merge_context(q, _ANSWER_HIST) == q


# ── SC1:R7 澄清闭环(末轮 clarify → 原问 + 澄清答)──────────────────────────
def test_merge_r7_closure():
    merged = merge_context("现行版本", _CLARIFY_HIST)
    assert "合同管理办法什么时候改的" in merged  # 原问
    assert "现行版本" in merged                   # 澄清答
    assert merged != "现行版本"                    # 已归并


# ── SC2:代词/省略顺承(继承上轮主题)──────────────────────────────────────
def test_merge_followup_pronoun():
    merged = merge_context("它的处罚呢", _ANSWER_HIST)  # 含指代「它」
    assert "内幕交易的认定标准" in merged              # 继承上轮主题
    assert "它的处罚呢" in merged


def test_merge_followup_too_short():
    merged = merge_context("这条", _ANSWER_HIST)  # 过短(< _MIN_LEN)
    assert "内幕交易的认定标准" in merged
    assert "这条" in merged


# ── SC4:LLM 为主 + fail-safe ───────────────────────────────────────────────
def test_merge_llm_primary_adopted():
    llm = _FakeLLM({"merged_query": "内幕交易的处罚标准"})
    assert merge_context("它的处罚呢", _ANSWER_HIST, llm=llm) == "内幕交易的处罚标准"
    assert llm.calls == 1


def test_merge_llm_raises_falls_back_to_rule():
    llm = _FakeLLM(raises=True)
    merged = merge_context("它的处罚呢", _ANSWER_HIST, llm=llm)  # LLM 抛 → 规则版兜
    assert "内幕交易的认定标准" in merged
    assert "它的处罚呢" in merged


def test_merge_llm_empty_falls_back_to_rule():
    llm = _FakeLLM({"merged_query": "   "})  # 空 → parse None → 规则版
    merged = merge_context("它的处罚呢", _ANSWER_HIST, llm=llm)
    assert "内幕交易的认定标准" in merged


def test_merge_llm_not_called_when_no_history():
    llm = _FakeLLM({"merged_query": "X"})
    assert merge_context("自足问句无需归并", [], llm=llm) == "自足问句无需归并"
    assert llm.calls == 0  # 空 history → 不触网络


# ── 坏/缺字段轮忽略(consumed-when-present)────────────────────────────────
def test_merge_ignores_bad_turns():
    hist = [
        "not a dict",
        {"role": "user"},                       # 缺 content
        {"content": "无 role"},                  # 缺 role
        {"role": "user", "content": "客户身份识别要求"},
        {"role": "assistant", "content": "请问现行还是历史?", "route_type": "clarify"},
    ]
    merged = merge_context("现行", hist)
    assert "客户身份识别要求" in merged  # 跳过坏轮,取有效 user 问
    assert "现行" in merged


def test_merge_all_bad_turns_noop():
    assert merge_context("它呢", ["x", {"foo": "bar"}]) == "它呢"  # 无有效 user 轮 → 原句


# ── parse_merged 畸形守护 ──────────────────────────────────────────────────
def test_parse_merged_variants():
    assert parse_merged({"merged_query": "ok"}) == "ok"
    assert parse_merged({"merged_query": "  trim  "}) == "trim"
    assert parse_merged({"merged_query": ""}) is None
    assert parse_merged({"merged_query": 123}) is None
    assert parse_merged({}) is None
    assert parse_merged("not a dict") is None


# ── prompt 红线:只改写、不作答、不编造(§7.1)────────────────────────────
def test_merge_system_prompt_no_fabrication():
    assert "不要回答" in MERGE_SYSTEM or "只改写" in MERGE_SYSTEM
    assert "编造" in MERGE_SYSTEM  # 禁编造制度名/发文字号/条款号
    user = build_merge_user("它呢", _ANSWER_HIST)
    assert "内幕交易的认定标准" in user  # 历史进 prompt
    assert "它呢" in user
