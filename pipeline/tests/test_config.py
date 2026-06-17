from pipeline.config import load_config


def test_load_config_defaults():
    c = load_config()
    # 七指标阈值齐全且取值符合 demo 默认
    assert c.qc.clause_coverage_min == 0.95
    assert c.qc.clause_continuity_max_gap == 0
    assert c.qc.page_anchor_complete_min == 1.0
    assert c.qc.edge_band_epsilon > 0
    # 对齐/解析/切块/批量 ⚠ 值可读
    assert 0 < c.align.fuzzy_threshold <= 100
    assert c.align.header_band_pct > 0
    assert c.parse.scanned_char_per_page_max == 50
    assert c.parse.parse_timeout_sec == 300
    assert c.chunk.target_token_min < c.chunk.target_token_max
    assert c.milvus.upsert_batch == 500
    assert c.milvus.collection == "audit_corpus"
    # M1 默认零 LLM
    assert c.toggles.l2_enabled is False
    assert c.embedding.mode in ("local", "endpoint")
    # profiles 抽检率字段保留(不消费)
    assert "P-INT" in c.profiles and "P-EXT" in c.profiles
    assert c.profiles["P-INT"].sampling_rate == 1.0
    # M2 验证组件阈值(T2/T4)
    assert c.verify.t2_synthetic_query_head_chars == 30
    assert c.verify.t2_hit_at == 50
    assert c.verify.t4_page_window == 1
    assert 0 < c.verify.t4_fuzzy_threshold <= 100
    # M3 E1 义务词表 + 阈值
    assert c.obligation.accuracy_threshold == 0.90
    assert "应当" in c.obligation.markers and "不得" in c.obligation.markers
    assert "相应" in c.obligation.exclusions and "无须" in c.obligation.exclusions  # X应/X须 排除
    assert c.obligation.bare_chars == ["应", "须"]
    assert c.obligation.markers and c.obligation.exclusions  # 非空


def test_env_override(monkeypatch):
    monkeypatch.setenv("PIPELINE_EMBEDDING_MODE", "endpoint")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://gw.local/v1")
    monkeypatch.setenv("PIPELINE_DB_DSN", "postgresql+psycopg://u:p@h:5432/x")
    c = load_config()
    assert c.embedding.mode == "endpoint"
    assert c.embedding.endpoint_base_url == "http://gw.local/v1"
    assert c.db.dsn.endswith("/x")
