"""T4:LLM 接缝默认 stub(零网络、确定性、从上下文选 clause_id)+ 工厂分发。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from query.config import QueryConfig
from query.llm import LLMClient, make_llm_client
from query.llm.stub import StubLLMClient


def test_default_backend_is_stub():
    c = make_llm_client(QueryConfig())  # 默认 llm_backend=stub
    assert isinstance(c, StubLLMClient)
    assert isinstance(c, LLMClient)  # 结构化满足 Protocol


def test_stub_selects_clause_ids_from_context_only():
    user = "候选:\n[[clause_id:AAA]] 第一条 ...\n[[clause_id:BBB]] 第二条 ..."
    out = StubLLMClient().chat_json("sys", user)
    assert out["cited_clause_ids"] == ["AAA", "BBB"]  # ⊆ 上下文,零编造
    assert "违规" not in out["answer"] and "合规" not in out["answer"]  # 无裸结论


def test_stub_dedups_and_caps():
    user = "[[clause_id:X]][[clause_id:X]][[clause_id:Y]][[clause_id:Z]][[clause_id:W]]"
    out = StubLLMClient(max_citations=3).chat_json("s", user)
    assert out["cited_clause_ids"] == ["X", "Y", "Z"]  # 去重保序 + 截断


def test_stub_empty_context():
    out = StubLLMClient().chat_json("s", "无标记上下文")
    assert out["cited_clause_ids"] == []


def test_unknown_backend_raises():
    cfg = QueryConfig()
    cfg.llm_backend = "bogus"  # 绕过构造校验(validate_assignment 默认关)测工厂防御分支
    with pytest.raises(ValueError, match="QUERY_LLM_BACKEND"):
        make_llm_client(cfg)


# ── §9.2:make_llm_client model 覆盖(add-only)—— gateway 传 model;默认 = llm_model ──────
def test_gateway_passes_explicit_review_model(monkeypatch):
    # 复核客户端传 review_model → gateway 用之建客户端(主答/复核模型分离,§9.1)。
    captured = {}
    monkeypatch.setattr(
        "pipeline.llm_client.make_llm_client",
        lambda model: captured.setdefault("model", model) or SimpleNamespace(),
    )
    cfg = QueryConfig(llm_backend="gateway", llm_model="qwen-main", review_model="kimi-review")
    make_llm_client(cfg, model=cfg.review_model)
    assert captured["model"] == "kimi-review"  # 收到 review_model,非主答 llm_model


def test_gateway_default_model_is_llm_model(monkeypatch):
    # 无 model 调用 = cfg.llm_model(向后兼容:既有 graph/调用零变化)。
    captured = {}
    monkeypatch.setattr(
        "pipeline.llm_client.make_llm_client",
        lambda model: captured.setdefault("model", model) or SimpleNamespace(),
    )
    cfg = QueryConfig(llm_backend="gateway", llm_model="qwen-main", review_model="kimi-review")
    make_llm_client(cfg)
    assert captured["model"] == "qwen-main"  # 默认走主答 llm_model


def test_stub_ignores_model():
    # stub 分支忽略 model(零网络,确定性);model 不影响返回 stub 实例。
    c = make_llm_client(QueryConfig(llm_backend="stub"), model="kimi-review")
    assert isinstance(c, StubLLMClient)
