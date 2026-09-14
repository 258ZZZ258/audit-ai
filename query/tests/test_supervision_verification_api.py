import json

from fastapi.testclient import TestClient

from query.api.app import create_app


def test_verification_auth_coverage_and_boolean(monkeypatch):
    monkeypatch.setenv("AUDIT_AI_INTERNAL_TOKEN", "test")
    app = create_app()

    class Client:
        calls = 0
        missing = False
        value = False

        def chat_json(self, system, user):
            self.calls += 1
            return {"verdicts": [] if self.missing else [
                {"id": c["id"], "supported": self.value, "reason": "原文未完成"}
                for c in json.loads(user)["claims"]
            ]}

    client = Client()
    app.state.supervision_association_client = client
    http = TestClient(app)
    data = {"claims": [{"id": "a", "field": "status", "value": "完成", "evidence": "未完成"}]}
    headers = {"X-Internal-Token": "test"}
    assert http.post("/v1/supervision/verify-fields", json=data).status_code == 401
    assert client.calls == 0
    response = http.post("/v1/supervision/verify-fields", json=data, headers=headers)
    assert response.status_code == 200
    assert response.json()["verdicts"][0]["supported"] is False
    client.missing = True
    assert http.post("/v1/supervision/verify-fields", json=data, headers=headers).status_code == 422
    client.missing = False
    client.value = "false"
    assert http.post("/v1/supervision/verify-fields", json=data, headers=headers).status_code == 422
    data["claims"].append(data["claims"][0])
    count = client.calls
    assert http.post("/v1/supervision/verify-fields", json=data, headers=headers).status_code == 422
    assert client.calls == count
