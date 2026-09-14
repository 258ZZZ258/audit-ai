"""监督提取 API 注册、服务令牌和失败语义；不连接生产数据库或模型。"""

import pytest
from fastapi.testclient import TestClient

from pipeline.supervision.service import SupervisionNotReady, SupervisionVersionNotFound
from query.api.app import create_app


def body():
    return {
        "metadata": {
            "documentId": "DOC-1",
            "documentVersionId": "DV-1",
            "fileName": "监管函.pdf",
            "categoryCode": "REG",
            "documentOrigin": "external",
            "organizationIds": ["ORG-1"],
            "uploadEntry": "supervision",
        },
        "organizations": [{"organizationId": "ORG-1", "name": "甲单位"}],
        "rules": [
            {
                "ruleId": "REG-1",
                "reportSection": "external.regulatory",
                "extractFields": [{"key": "problem", "description": "问题事实"}],
            }
        ],
    }


class Service:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def extract(self, request):
        self.calls.append(request)
        if self.error:
            raise self.error
        return {"extractionStatus": "EVIDENCE_READY", "facts": []}


def client(monkeypatch, error=None):
    monkeypatch.setenv("AUDIT_AI_INTERNAL_TOKEN", "test-token")
    app = create_app()
    app.state.supervision_service = Service(error)
    return TestClient(app, raise_server_exceptions=False), app.state.supervision_service


def test_supervision_requires_internal_token_without_calling_service(monkeypatch):
    c, svc = client(monkeypatch)
    assert c.post("/v1/supervision/extract", json=body()).status_code == 401
    assert not svc.calls
    monkeypatch.delenv("AUDIT_AI_INTERNAL_TOKEN")
    assert (
        c.post(
            "/v1/supervision/extract", json=body(), headers={"X-Internal-Token": "test-token"}
        ).status_code
        == 401
    )


def test_supervision_route_accepts_java_metadata(monkeypatch):
    c, svc = client(monkeypatch)
    r = c.post("/v1/supervision/extract", json=body(), headers={"X-Internal-Token": "test-token"})
    assert r.status_code == 200
    assert r.json()["extractionStatus"] == "EVIDENCE_READY"
    assert svc.calls[0].metadata.documentVersionId == "DV-1"


@pytest.mark.parametrize(
    "error,status",
    [
        (SupervisionNotReady("not indexed"), 409),
        (SupervisionVersionNotFound("missing"), 404),
        (KeyError("sensitive model output"), 500),
        (ValueError("sensitive body"), 422),
        (RuntimeError("sensitive API key"), 500),
    ],
)
def test_supervision_failure_is_not_empty_success(monkeypatch, error, status):
    c, _svc = client(monkeypatch, error)
    r = c.post("/v1/supervision/extract", json=body(), headers={"X-Internal-Token": "test-token"})
    assert r.status_code == status
    assert "sensitive" not in r.text


def test_supervision_rejects_client_claimed_index_status(monkeypatch):
    c, svc = client(monkeypatch)
    raw = body()
    raw["metadata"]["processingStatus"] = "indexed"
    r = c.post("/v1/supervision/extract", json=raw, headers={"X-Internal-Token": "test-token"})
    assert r.status_code == 422
    assert not svc.calls
