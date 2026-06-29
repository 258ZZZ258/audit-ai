"""T2/T4(单元,零栈零网络):N1 HyDE retrieve/hyde.py 纯函数 + Retriever._dense_for 接缝。

T2 覆盖 SC1(生成)/SC3(fail-safe)/SC7(不臆造);T4 覆盖 SC1/SC2(no-op)/SC3(回落)/SC6(仅主 retrieve)。
HyDE 只改 dense、绝不产出 clause_id(§7.1);LLM 失败 → None → 调用方回落原问 dense(绝不阻断)。
"""

from __future__ import annotations

from query.retrieve.hyde import (
    HYDE_SYSTEM,
    build_hyde_user,
    hyde_dense_text,
    parse_passage,
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


_Q = "二维码介绍开户违不违规"


# ── parse_passage 畸形守护 ─────────────────────────────────────────────────
def test_parse_passage_variants():
    assert parse_passage({"passage": "金融机构应当核实客户身份。"}) == "金融机构应当核实客户身份。"
    assert parse_passage({"passage": "  trim  "}) == "trim"
    assert parse_passage({"passage": ""}) is None
    assert parse_passage({"passage": 123}) is None
    assert parse_passage({}) is None
    assert parse_passage("not a dict") is None


# ── hyde_dense_text:生成 + fail-safe(SC1/SC3)─────────────────────────────
def test_hyde_dense_text_generates():
    llm = _FakeLLM({"passage": "经营机构不得违规招揽客户、不得居间介绍开户。"})
    out = hyde_dense_text(_Q, llm)
    assert out is not None
    assert out.startswith(_Q)                                  # 原问在前(一同送入 dense)
    assert "违规招揽客户" in out                                # 假设性法言并入
    assert llm.calls == 1


def test_hyde_dense_text_llm_raises_returns_none():
    assert hyde_dense_text(_Q, _FakeLLM(raises=True)) is None  # 抛 → None → 调用方回落原问


def test_hyde_dense_text_empty_returns_none():
    assert hyde_dense_text(_Q, _FakeLLM({"passage": "   "})) is None
    assert hyde_dense_text(_Q, _FakeLLM({})) is None


# ── prompt 红线:只写假设性法言、不作答、不编造(§7.1)──────────────────────
def test_hyde_system_prompt_no_fabrication():
    assert "假设" in HYDE_SYSTEM
    assert "不要回答" in HYDE_SYSTEM or "只写" in HYDE_SYSTEM
    assert "编造" in HYDE_SYSTEM  # 禁编造发文字号/条款号
    user = build_hyde_user(_Q)
    assert _Q in user
