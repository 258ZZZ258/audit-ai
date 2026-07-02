"""T4(SPEC-API §9/§15):FastAPI 骨架错误语义 + healthz + 鉴权 stub。

TestClient 免真栈:错误机器(自定义/校验/未知路径/未处理)统一渲染 {"error":{code,message,details?}};
500 不泄内部细节;healthz 不碰真栈;导出权限点 stub 放行 + 无权 403。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from query.api.errors import (
    ApiError,
    install_error_handlers,
    not_found,
    payload_too_large,
)


def _debug_client() -> TestClient:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/nf")
    def _nf():
        raise not_found("会话不存在")

    @app.get("/pl")
    def _pl():
        raise payload_too_large()

    @app.get("/need-int")
    def _need_int(x: int):
        return {"x": x}

    @app.get("/crash")
    def _crash():
        raise RuntimeError("secret internal stacktrace detail")

    return TestClient(app, raise_server_exceptions=False)


def test_api_error_body_and_status():
    c = _debug_client()
    r = c.get("/nf")
    assert r.status_code == 404
    assert r.json() == {"error": {"code": "NOT_FOUND", "message": "会话不存在"}}
    r = c.get("/pl")
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_validation_error_422_unified_shape():
    r = _debug_client().get("/need-int")  # 缺必填 x → RequestValidationError
    assert r.status_code == 422
    body = r.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "details" in body["error"]


def test_unknown_path_404_unified_shape():
    r = _debug_client().get("/does-not-exist")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"


def test_unhandled_500_no_detail_leak():
    r = _debug_client().get("/crash")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "secret" not in r.text  # 内部细节不回客户端


def test_healthz_no_stack():
    from query.api.app import create_app

    r = TestClient(create_app()).get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_export_permission_stub_allow_and_deny():
    from query.api.auth import Principal, current_principal, require_export_permission

    assert current_principal().can_export is True
    require_export_permission(Principal(can_export=True))  # 放行:不抛
    with pytest.raises(ApiError) as ei:
        require_export_permission(Principal(can_export=False))
    assert ei.value.status == 403 and ei.value.code == "FORBIDDEN"
