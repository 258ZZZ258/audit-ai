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


def test_review_model_default_and_env(tmp_path, monkeypatch):
    # §9.2 复核模型(Kimi):默认 kimi-2.5(§9.1 意图占位);QUERY_REVIEW_MODEL 覆盖。
    (tmp_path / "settings.toml").write_text("[query]\n", encoding="utf-8")
    assert load_query_config(tmp_path).review_model == "kimi-2.5"
    monkeypatch.setenv("QUERY_REVIEW_MODEL", "kimi-2.5-turbo")
    assert load_query_config(tmp_path).review_model == "kimi-2.5-turbo"


def test_review_model_openai_alias_and_precedence(tmp_path, monkeypatch):
    # OPENAI_REVIEW_MODEL 亦覆盖;两者并存时 QUERY_REVIEW_MODEL(query 专属)优先。
    (tmp_path / "settings.toml").write_text("[query]\n", encoding="utf-8")
    monkeypatch.setenv("OPENAI_REVIEW_MODEL", "kimi-openai-alias")
    assert load_query_config(tmp_path).review_model == "kimi-openai-alias"
    monkeypatch.setenv("QUERY_REVIEW_MODEL", "kimi-query-specific")
    assert load_query_config(tmp_path).review_model == "kimi-query-specific"


def test_merge_context_defaults(tmp_path):
    # N0 多轮归并:默认开(已决①,LLM 为主);merge_model 默认 None → 复用主答 llm_model。
    (tmp_path / "settings.toml").write_text("[query]\n", encoding="utf-8")
    cfg = load_query_config(tmp_path)
    assert cfg.merge_context is True   # §3.4 N0 默认开
    assert cfg.merge_model is None     # None → 归并复用 llm_model


def test_merge_context_env_override(tmp_path, monkeypatch):
    (tmp_path / "settings.toml").write_text("[query]\n", encoding="utf-8")
    monkeypatch.setenv("QUERY_MERGE_CONTEXT", "0")  # 关 → "0" → bool False
    monkeypatch.setenv("QUERY_MERGE_MODEL", "qwen-turbo")
    cfg = load_query_config(tmp_path)
    assert cfg.merge_context is False
    assert cfg.merge_model == "qwen-turbo"


def test_hyde_defaults(tmp_path):
    # N1 HyDE:默认开(已决①,对齐设计 §3 节点链);hyde_model 默认 None → 复用主答 llm_model。
    (tmp_path / "settings.toml").write_text("[query]\n", encoding="utf-8")
    cfg = load_query_config(tmp_path)
    assert cfg.hyde is True        # §3.1 默认开(真 HyDE 仅 gateway 活;stub→no-op)
    assert cfg.hyde_model is None  # None → HyDE 复用 llm_model


def test_hyde_env_override(tmp_path, monkeypatch):
    (tmp_path / "settings.toml").write_text("[query]\n", encoding="utf-8")
    monkeypatch.setenv("QUERY_HYDE", "0")  # 关 → "0" → bool False
    monkeypatch.setenv("QUERY_HYDE_MODEL", "qwen-turbo")
    cfg = load_query_config(tmp_path)
    assert cfg.hyde is False
    assert cfg.hyde_model == "qwen-turbo"


def test_decompose_defaults(tmp_path):
    # N3 问题分解:默认开(已决②);decompose_model 默认 None;max_sub 默认 4(⚠ V0 封顶)。
    (tmp_path / "settings.toml").write_text("[query]\n", encoding="utf-8")
    cfg = load_query_config(tmp_path)
    assert cfg.decompose is True        # §3.3 默认开(仅复合触发;stub→单查询 no-op)
    assert cfg.decompose_model is None  # None → 复用 llm_model
    assert cfg.decompose_max_sub == 4   # ⚠ V0 fan-out 上限


def test_decompose_env_override(tmp_path, monkeypatch):
    (tmp_path / "settings.toml").write_text("[query]\n", encoding="utf-8")
    monkeypatch.setenv("QUERY_DECOMPOSE", "0")  # 关 → "0" → bool False
    monkeypatch.setenv("QUERY_DECOMPOSE_MODEL", "qwen-turbo")
    cfg = load_query_config(tmp_path)
    assert cfg.decompose is False
    assert cfg.decompose_model == "qwen-turbo"


def test_observe_default_and_env(tmp_path, monkeypatch):
    # §9.3 Langfuse 观测:默认关(观测外发外部服务、守零网络;区别于 N0/N1/N3 默认开)。
    (tmp_path / "settings.toml").write_text("[query]\n", encoding="utf-8")
    assert load_query_config(tmp_path).observe is False  # 默认关 → Noop 零网络
    monkeypatch.setenv("QUERY_OBSERVE", "1")
    assert load_query_config(tmp_path).observe is True


def test_sparse_boost_defaults(tmp_path):
    (tmp_path / "settings.toml").write_text("[query]\n", encoding="utf-8")
    cfg = load_query_config(tmp_path)
    assert cfg.docnum_boost is False  # §5.4 默认关 → byte 等价
    assert cfg.scenario_expand is False
    assert cfg.docnum_boost_factor == 2.0  # ⚠ V0 占位
    assert cfg.scenario_expand_factor == 1.0
    assert "seeds" in cfg.scenario_terms_path  # 默认锚 repo 根 seeds/
    assert cfg.scenario_terms_path.endswith("dict_scenario_terms.csv")


def test_sparse_boost_env_override(tmp_path, monkeypatch):
    (tmp_path / "settings.toml").write_text("[query]\n", encoding="utf-8")
    monkeypatch.setenv("QUERY_DOCNUM_BOOST", "1")
    monkeypatch.setenv("QUERY_SCENARIO_EXPAND", "1")
    monkeypatch.setenv("QUERY_SCENARIO_TERMS_PATH", "/tmp/x.csv")
    cfg = load_query_config(tmp_path)
    assert cfg.docnum_boost is True  # "1" → bool 强转
    assert cfg.scenario_expand is True
    assert cfg.scenario_terms_path == "/tmp/x.csv"
