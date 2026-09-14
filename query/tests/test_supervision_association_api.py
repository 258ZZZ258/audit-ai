import json

from fastapi.testclient import TestClient

from query.api.app import create_app


def test_association_auth_evidence_and_coverage(monkeypatch):
    monkeypatch.setenv("AUDIT_AI_INTERNAL_TOKEN", "test")
    app = create_app()

    class Client:
        calls = 0
        quote = "已登记设备"

        def chat_json(self, system, user):
            self.calls += 1
            return {"decisions": [dict(pairId=p["pairId"], verdict="MATCH", reason="设备登记对应",
                                       issueQuote=p["issueText"], recordQuote=self.quote)
                                  for p in json.loads(user)["pairs"]]}

    client = Client()
    app.state.supervision_association_client = client
    http = TestClient(app)
    body = {"pairs": [dict(pairId="p", issueText="设备未登记", recordText="已登记设备")]}
    headers = {"X-Internal-Token": "test"}
    assert http.post("/v1/supervision/associate", json=body).status_code == 401
    assert client.calls == 0
    assert http.post("/v1/supervision/associate", json=body, headers=headers).status_code == 200
    client.quote = "不存在的证据"
    assert http.post("/v1/supervision/associate", json=body, headers=headers).status_code == 422
    body["pairs"].append(body["pairs"][0])
    assert http.post("/v1/supervision/associate", json=body, headers=headers).status_code == 422
    assert client.calls == 2


def test_association_model_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("AUDIT_AI_INTERNAL_TOKEN", "test")
    config = tmp_path / "supervision.toml"
    config.write_text('backend="none"\nmax_evidence_chars=16000\n', encoding="utf-8")
    monkeypatch.setenv("SUPERVISION_CONFIG", str(config))
    http = TestClient(create_app())
    response = http.post("/v1/supervision/associate", headers={"X-Internal-Token": "test"},
                         json={"pairs": [dict(pairId="p", issueText="问题", recordText="整改")]})
    assert response.status_code == 503
