"""T8(SPEC-API §8.4):文件上传端点 —— 白名单 415 / 超限 413 / 只存不消费 + 注册 upload_id。"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from query.api.app import create_app

_PREFIX = "/api/query/v1"
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _client(tmp_path, max_bytes=50 * 1024 * 1024):
    qcfg = SimpleNamespace(upload_dir=str(tmp_path), max_upload_bytes=max_bytes)
    svc = SimpleNamespace(qcfg=qcfg, uploads={})
    return TestClient(create_app(service=svc)), svc


def test_upload_pdf_201_stored_and_registered(tmp_path):
    c, svc = _client(tmp_path)
    payload = b"%PDF-1.4 fake data"
    r = c.post(f"{_PREFIX}/uploads", files={"file": ("report.pdf", payload, "application/pdf")})
    assert r.status_code == 201
    body = r.json()
    assert body["filename"] == "report.pdf" and body["content_type"] == "application/pdf"
    assert body["size"] == len(payload)
    uid = body["upload_id"]
    assert uid in svc.uploads                 # 注册(供附件引用校验)
    assert (tmp_path / uid).exists()          # 只存:文件落盘


def test_upload_non_whitelist_returns_415(tmp_path):
    c, _ = _client(tmp_path)
    r = c.post(f"{_PREFIX}/uploads", files={"file": ("note.txt", b"hello", "text/plain")})
    assert r.status_code == 415 and r.json()["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"


def test_upload_oversize_returns_413(tmp_path):
    c, _ = _client(tmp_path, max_bytes=10)
    r = c.post(f"{_PREFIX}/uploads", files={"file": ("big.xlsx", b"x" * 20, _XLSX)})
    assert r.status_code == 413 and r.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_upload_by_extension_when_content_type_generic(tmp_path):
    c, _ = _client(tmp_path)
    # 浏览器有时给 application/octet-stream → 按扩展名放行
    files = {"file": ("f.docx", b"data", "application/octet-stream")}
    assert c.post(f"{_PREFIX}/uploads", files=files).status_code == 201
