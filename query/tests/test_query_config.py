"""T3:[query] 段加载 + 缺省值 + env 覆盖。"""

from __future__ import annotations

from query.config import QueryConfig, load_query_config


def test_load_defaults_from_repo_settings():
    cfg = load_query_config()
    assert cfg.llm_backend == "stub"          # 默认零网络
    assert cfg.rerank_backend == "none"       # 默认用 RRF 序
    assert cfg.topk >= 1
    assert cfg.partition_topk >= cfg.topk      # 分区召回 ≥ 最终上下文


def test_missing_query_section_uses_defaults(tmp_path):
    (tmp_path / "settings.toml").write_text("[db]\ndsn = 'x'\n", encoding="utf-8")
    assert load_query_config(tmp_path) == QueryConfig()  # 缺 [query] 段 → 全默认


def test_env_override_llm_backend(tmp_path, monkeypatch):
    (tmp_path / "settings.toml").write_text("[query]\nllm_backend = 'stub'\n", encoding="utf-8")
    monkeypatch.setenv("QUERY_LLM_BACKEND", "gateway")
    assert load_query_config(tmp_path).llm_backend == "gateway"


def test_rerank_model_default_and_env(tmp_path, monkeypatch):
    (tmp_path / "settings.toml").write_text("[query]\n", encoding="utf-8")
    assert load_query_config(tmp_path).rerank_model == "BAAI/bge-reranker-v2-m3"  # §5.5 默认
    monkeypatch.setenv("QUERY_RERANK_MODEL", "/local/bge-reranker")
    assert load_query_config(tmp_path).rerank_model == "/local/bge-reranker"
