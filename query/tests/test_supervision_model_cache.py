import json

from fastapi.testclient import TestClient

from pipeline.llm_client import LLMError
from query.api.app import create_app


def test_model_cache_retry_input_invalidation_and_auth(monkeypatch, tmp_path):
    config = tmp_path / "supervision.toml"
    config.write_text('backend="gateway"\nmax_evidence_chars=16000\n', encoding="utf-8")
    monkeypatch.setenv("SUPERVISION_CONFIG", str(config))
    monkeypatch.setenv("AUDIT_AI_INTERNAL_TOKEN", "test")
    monkeypatch.setenv("OPENAI_API_KEY", "fake")

    class Client:
        model = "test-model"
        calls = 0

        def chat_json(self, system, user):
            self.calls += 1
            if self.calls == 1:
                raise LLMError("transient")
            return {"verdicts": [
                {"id": c["id"], "supported": False, "reason": "证据不足"}
                for c in json.loads(user)["claims"]
            ]}

    client = Client()
    monkeypatch.setattr("query.api.routes_supervision.make_llm_client", lambda **kw: client)
    http = TestClient(create_app())
    headers = {"X-Internal-Token": "test"}
    body = {"claims": [{"id": "a", "field": "status", "value": "已完成", "evidence": "未完成"}]}
    for _ in range(2):
        response = http.post("/v1/supervision/verify-fields", json=body, headers=headers)
        assert response.status_code == 200
    assert client.calls == 2
    assert http.post("/v1/supervision/verify-fields", json=body).status_code == 401
    body["claims"][0]["evidence"] = "部分完成"
    assert http.post("/v1/supervision/verify-fields", json=body, headers=headers).status_code == 200
    assert client.calls == 3
    client.model = "new-model"
    assert http.post("/v1/supervision/verify-fields", json=body, headers=headers).status_code == 200
    assert client.calls == 4
