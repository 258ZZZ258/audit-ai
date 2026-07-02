"""T8(SPEC-API §8.2):推荐问题端点 —— config 驱动(非硬编码进端点)。"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from query.api.app import create_app

_PREFIX = "/api/query/v1"


def test_suggestions_from_config():
    svc = SimpleNamespace(qcfg=SimpleNamespace(suggestions=["Q1", "Q2", "Q3", "Q4"]))
    r = TestClient(create_app(service=svc)).get(f"{_PREFIX}/suggestions")
    assert r.status_code == 200
    assert r.json() == {"items": ["Q1", "Q2", "Q3", "Q4"]}


def test_default_config_provides_four_suggestions():
    from query.config import load_query_config

    sug = load_query_config().suggestions   # config 驱动(settings.toml [query] 可覆盖)
    assert len(sug) == 4 and all(isinstance(s, str) and s for s in sug)
