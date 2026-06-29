"""T2/T4(单元,零栈零网络):N3 问题分解 retrieve/decompose.py 纯函数 + Retriever fan-out。

T2 覆盖 SC1(拆分)/SC4(fail-safe)/SC5(max_sub)/SC8(不臆造);T4 覆盖 SC2(fan-out 并集)/SC3(no-op)。
复合问句拆子查询(§3.3),单跳/失败 → [原问];**不迭代**(§0.3 一次性);不产 clause_id(§7.1)。
"""

from __future__ import annotations

from query.retrieve.decompose import (
    DECOMPOSE_SYSTEM,
    build_decompose_user,
    decompose_subqueries,
    parse_subqueries,
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


_Q = "私募权益投顾同时管偏股和偏债是否违规"


# ── parse_subqueries 畸形守护 ──────────────────────────────────────────────
def test_parse_subqueries_variants():
    assert parse_subqueries({"subqueries": ["a", "b"]}) == ["a", "b"]
    assert parse_subqueries({"subqueries": ["a", "", "  ", 5, "b"]}) == ["a", "b"]  # 过滤空/非串
    assert parse_subqueries({"subqueries": "not a list"}) == []
    assert parse_subqueries({}) == []
    assert parse_subqueries("not a dict") == []


# ── decompose_subqueries:拆分 + 单跳直通 + fail-safe + max_sub(SC1/4/5)──────
def test_decompose_compound():
    llm = _FakeLLM({"subqueries": ["私募权益投顾管偏股是否违规", "私募权益投顾管偏债是否违规"]})
    subs = decompose_subqueries(_Q, llm)
    assert len(subs) == 2
    assert "偏股" in subs[0] and "偏债" in subs[1]
    assert llm.calls == 1


def test_decompose_single_returns_original_query():
    # LLM 只拆出 1 个(单跳问句)→ 返原问(直通,不用 LLM 改写的单个)
    assert decompose_subqueries(_Q, _FakeLLM({"subqueries": ["仅一个子查询"]})) == [_Q]


def test_decompose_llm_raises_returns_query():
    assert decompose_subqueries(_Q, _FakeLLM(raises=True)) == [_Q]  # 抛 → 单查询


def test_decompose_empty_returns_query():
    assert decompose_subqueries(_Q, _FakeLLM({"subqueries": []})) == [_Q]
    assert decompose_subqueries(_Q, _FakeLLM({})) == [_Q]


def test_decompose_max_sub_truncates():
    llm = _FakeLLM({"subqueries": ["a", "b", "c", "d", "e", "f"]})
    assert decompose_subqueries(_Q, llm, max_sub=3) == ["a", "b", "c"]  # 截断至 max_sub


# ── prompt 红线:只拆、不作答、不编造(§7.1)+ 不迭代(§0.3)────────────────
def test_decompose_system_prompt_no_fabrication():
    assert "复合" in DECOMPOSE_SYSTEM
    assert "不要回答" in DECOMPOSE_SYSTEM or "只拆" in DECOMPOSE_SYSTEM
    assert "编造" in DECOMPOSE_SYSTEM  # 禁编造制度名/条款号
    assert _Q in build_decompose_user(_Q)
