"""Standard-library HTTP app for the demo workbench.

Run with:

    demo-web --host 127.0.0.1 --port 8765
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from pipeline.web import service

STATIC_DIR = Path(__file__).with_name("static")

#: 上传/请求体大小上限(demo 自我保护:防超大 POST 撑爆单进程内存/磁盘)。Content-Length 超限即 413。
_MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 整批原件 + manifest
_MAX_JSON_BYTES = 1 * 1024 * 1024  # API JSON 体


class _PayloadTooLarge(Exception):
    """请求体超过上限 → 413(不读入内存,据 Content-Length 预先拒绝)。"""


def _json_default(value):
    return service._jsonable(value)


class WorkbenchHandler(BaseHTTPRequestHandler):
    server_version = "PipelineWorkbench/0.1"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path.startswith("/api/"):
                self._handle_api_get(parsed.path, parse_qs(parsed.query))
            else:
                self._serve_static(parsed.path)
        except Exception as exc:  # noqa: BLE001
            self._send_error(exc)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            self._handle_api_post(parsed.path, parse_qs(parsed.query))
        except Exception as exc:  # noqa: BLE001
            self._send_error(exc)

    def log_message(self, fmt: str, *args) -> None:
        print(f"[web] {self.address_string()} - {fmt % args}")

    # ── API routing ───────────────────────────────────────────
    def _handle_api_get(self, path: str, qs: dict[str, list[str]]) -> None:
        if path == "/api/overview":
            return self._send_json(service.overview())
        if path == "/api/batches":
            return self._send_json({"batches": service.batches()})
        if path.startswith("/api/batches/"):
            batch_id = path.removeprefix("/api/batches/").split("/", 1)[0]
            return self._send_json(service.batch_detail(batch_id))
        if path == "/api/queue":
            show_all = qs.get("all", ["false"])[0].lower() == "true"
            return self._send_json({"items": service.queue_items(show_all)})
        if path.startswith("/api/docs/") and "/artifacts/" in path:
            return self._send_artifact(path)
        if path.startswith("/api/docs/"):
            dvid = path.removeprefix("/api/docs/").split("/", 1)[0]
            return self._send_json(service.doc_detail(dvid))
        self._send_json(_not_found(), status=HTTPStatus.NOT_FOUND)

    def _handle_api_post(self, path: str, qs: dict[str, list[str]]) -> None:
        if path == "/api/upload":
            return self._send_json(service.ingest_upload(**self._parse_upload()))
        if path == "/api/search":  # 边界校验:显式取字段 + 强转 + 夹值,不展开 **body
            body = self._read_json()
            query = (body.get("query") or "").strip()
            if not query:
                raise ValueError("query 必填")
            topk = max(1, min(_as_int(body.get("topk"), 10), 50))  # 夹 [1,50],防昂贵查询
            return self._send_json(
                service.search(
                    query,
                    topk=topk,
                    include_superseded=bool(body.get("include_superseded")),
                    corpus=body.get("corpus"),
                )
            )
        if path == "/api/meta/confirm":
            body = self._read_json()
            return self._send_json(
                service.approve_meta(
                    queue_id=body.get("queue_id"),
                    batch_id=body.get("batch_id"),
                    operator=str(body.get("operator") or "web"),
                )
            )
        if path == "/api/meta/resolve":  # 一键采用某冲突字段的 L1 抽取值
            body = self._read_json()
            queue_id, field, value = body.get("queue_id"), body.get("field"), body.get("value")
            if not queue_id or not field or value is None:
                raise ValueError("queue_id / field / value 必填")
            return self._send_json(
                service.apply_meta_suggestion(
                    str(queue_id),
                    str(field),
                    str(value),
                    operator=str(body.get("operator") or "web"),
                )
            )
        if path.startswith("/api/queue/"):
            parts = path.strip("/").split("/")
            if len(parts) != 4:
                raise ValueError("queue action path must be /api/queue/{id}/{action}")
            _api, _queue, qid, action = parts
            body = self._read_json(default={})
            return self._send_json(
                service.dispose_queue(qid, action, operator=body.get("operator", "web"))
            )
        if path == "/api/reprocess":
            body = self._read_json()
            dvid = body.get("doc_version_id")
            if not dvid:
                raise ValueError("doc_version_id 必填")
            return self._send_json(
                service.reprocess_doc(dvid, operator=str(body.get("operator") or "web"))
            )
        if path.startswith("/api/verify/"):
            name = path.removeprefix("/api/verify/")
            body = self._read_json(default={})
            return self._send_json(service.run_verify(name, body.get("batch_id")))
        if path == "/api/report":
            body = self._read_json()
            batch_id = body.get("batch_id")
            if not batch_id:
                raise ValueError("batch_id 必填")
            return self._send_json(service.batch_report(batch_id))
        self._send_json(_not_found(), status=HTTPStatus.NOT_FOUND)

    # ── Request parsing ───────────────────────────────────────
    def _read_body(self, max_bytes: int) -> bytes:
        """按 Content-Length 读体,**超限先拒**(不读入内存)→ 413。缺/0 长度返空。"""
        length = int(self.headers.get("content-length", "0") or "0")
        if length > max_bytes:
            raise _PayloadTooLarge(f"请求体过大({length} 字节,上限 {max_bytes})")
        return self.rfile.read(length) if length > 0 else b""

    def _read_json(self, default=None) -> dict:
        raw = self._read_body(_MAX_JSON_BYTES)
        if not raw:
            return default if default is not None else {}
        return json.loads(raw.decode("utf-8") or "{}")

    def _parse_upload(self) -> dict:
        ctype, params = _parse_content_type(self.headers.get("content-type", ""))
        if ctype != "multipart/form-data":
            raise ValueError("上传请求必须使用 multipart/form-data")
        boundary = params.get("boundary")
        if not boundary:
            raise ValueError("multipart/form-data 缺 boundary")
        text, file_parts = _parse_multipart(self._read_body(_MAX_UPLOAD_BYTES), boundary)
        files: list[service.UploadedFile] = []
        manifest = None
        for field_name, filename, data in file_parts:
            item = service.UploadedFile(Path(filename).name, data)
            if field_name == "manifest" or item.filename.lower().endswith(".xlsx"):
                manifest = item
            else:
                files.append(item)
        return {
            "files": files,
            "manifest": manifest,
            "corpus_type": text.get("corpus_type", "auto"),
            "perm_tag": text.get("perm_tag", "内部"),
            "biz_domain": text.get("biz_domain", "GENERAL"),
            "issuer": text.get("issuer", "DEMO"),
        }

    # ── Responses/static ──────────────────────────────────────
    def _send_json(self, payload, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False, default=_json_default).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_artifact(self, path: str) -> None:
        parts = path.strip("/").split("/")
        if len(parts) != 5:
            raise ValueError("artifact path must be /api/docs/{id}/artifacts/{kind}")
        _api, _docs, dvid, _artifacts, kind = parts
        artifact = service.artifact_file(dvid, kind)
        self.send_response(HTTPStatus.OK)
        self.send_header("content-type", artifact.content_type)
        self.send_header("content-length", str(len(artifact.data)))
        self.send_header(
            "content-disposition",
            f"inline; filename*=UTF-8''{quote(artifact.filename)}",
        )
        self.end_headers()
        self.wfile.write(artifact.data)

    def _send_error(self, exc: Exception) -> None:
        """统一错误语义:域异常 → 4xx/409;未预期 → 500 通用文案。"""
        if isinstance(exc, _PayloadTooLarge):
            status, code = HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "PAYLOAD_TOO_LARGE"
            msg = str(exc)
        elif isinstance(exc, KeyError):
            status, code = HTTPStatus.NOT_FOUND, "NOT_FOUND"
            msg = f"未找到: {exc.args[0] if exc.args else exc}"
        elif isinstance(exc, ValueError):
            status, code = HTTPStatus.BAD_REQUEST, "BAD_INPUT"
            msg = str(exc)
        elif isinstance(exc, RuntimeError):  # 域处理失败(管线未达终态 / 投影清理失败),可重试
            status, code = HTTPStatus.CONFLICT, "PIPELINE_FAILED"
            msg = str(exc)
        else:  # 未预期:500 + 通用文案,细节只记服务端日志,不向客户端泄露内部堆栈/类型
            status, code = HTTPStatus.INTERNAL_SERVER_ERROR, "INTERNAL"
            self.log_message("unhandled %s: %s", exc.__class__.__name__, exc)
            msg = "服务器内部错误"
        self._send_json({"error": {"code": code, "message": msg}}, status=status)

    def _serve_static(self, path: str) -> None:
        rel = "index.html" if path in {"", "/"} else path.lstrip("/")
        target = (STATIC_DIR / rel).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.exists():
            target = STATIC_DIR / "index.html"
        data = target.read_bytes()
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _not_found() -> dict:
    return {"error": {"code": "NOT_FOUND", "message": "路由不存在"}}


def _as_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_content_type(value: str) -> tuple[str, dict[str, str]]:
    """解析 ``Content-Type`` 头为 (主类型, 参数dict);替代已弃用的 ``cgi.parse_header``。"""
    parts = value.split(";")
    main = parts[0].strip().lower()
    params: dict[str, str] = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            params[k.strip().lower()] = v.strip().strip('"')
    return main, params


_DISPOSITION_PARAM = re.compile(rb'(\w+)="([^"]*)"')


def _parse_disposition(head: bytes) -> dict[str, str]:
    """从 part 头部抽 Content-Disposition 的 name / filename。"""
    out: dict[str, str] = {}
    for line in head.split(b"\r\n"):
        if line.lower().startswith(b"content-disposition:"):
            for m in _DISPOSITION_PARAM.finditer(line):
                out[m.group(1).decode("latin-1")] = m.group(2).decode("utf-8", "replace")
    return out


def _parse_multipart(
    body: bytes, boundary: str
) -> tuple[dict[str, str], list[tuple[str, str, bytes]]]:
    """极简 multipart/form-data 解析(**纯标准库**,替代 3.13 移除的 ``cgi.FieldStorage``)。

    返回 ``(text_fields, file_parts)``,file_parts=``[(field_name, filename, data)]``。
    **保二进制完整**:只剥分隔符框定的那一对 CRLF,绝不动体内字节(文件含 \\r\\n / 以换行结尾均无损)。
    """
    delim = b"--" + boundary.encode("latin-1")
    text: dict[str, str] = {}
    files: list[tuple[str, str, bytes]] = []
    for seg in body.split(delim):
        if seg.startswith(b"\r\n"):  # 仅剥框定 CRLF(前导一处)
            seg = seg[2:]
        if seg.endswith(b"\r\n"):  # 框定 CRLF(尾随一处)
            seg = seg[:-2]
        if not seg or seg == b"--":  # 序言 / 结束标记(--boundary--)
            continue
        head, sep, data = seg.partition(b"\r\n\r\n")
        if not sep:
            continue
        disp = _parse_disposition(head)
        name = disp.get("name")
        if name is None:
            continue
        filename = disp.get("filename")
        if filename:
            files.append((name, filename, data))
        else:
            text[name] = data.decode("utf-8", "replace")
    return text, files


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="运行本地文档管线工作台")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    httpd = ThreadingHTTPServer((args.host, args.port), WorkbenchHandler)
    print(f"Workbench running at http://{args.host}:{args.port}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
