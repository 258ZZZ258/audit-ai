"""T8(SPEC-API §8.2/§8.4):推荐问题 + 文件上传。

``GET /suggestions`` → config 驱动的首页引导问句(非硬编码)。
``POST /uploads`` → multipart 附件:白名单 PDF/Word/Excel(415)+ ≤上限(413)+ **只存不消费**,
返 ``upload_id`` 供提问 ``attachments`` 引用。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Query, UploadFile
from ulid import ULID

from query.api.errors import payload_too_large, unsupported_media
from query.api.service import QueryService, get_service

router = APIRouter(tags=["misc"])

_ALLOWED_CT = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
_ALLOWED_EXT = (".pdf", ".doc", ".docx", ".xls", ".xlsx")
_DEFAULT_MAX = 50 * 1024 * 1024


@router.get("/suggestions")
def suggestions(
    agent_type: str = Query("institution_query"),  # 预留:功能2 后可按类型返回不同集
    svc: QueryService = Depends(get_service),
) -> dict:
    return {"items": list(getattr(svc.qcfg, "suggestions", []))}


@router.post("/uploads", status_code=201)
def upload(file: UploadFile = File(...), svc: QueryService = Depends(get_service)) -> dict:
    _check_content_type(file)
    max_bytes = getattr(svc.qcfg, "max_upload_bytes", _DEFAULT_MAX)
    data = _read_bounded(file, max_bytes)
    upload_id = str(ULID())
    updir = Path(getattr(svc.qcfg, "upload_dir", None) or _default_dir())
    updir.mkdir(parents=True, exist_ok=True)
    (updir / upload_id).write_bytes(data)
    meta = {
        "upload_id": upload_id, "filename": file.filename,
        "size": len(data), "content_type": file.content_type,
    }
    svc.uploads[upload_id] = {**meta, "path": str(updir / upload_id)}  # 只存不消费
    return meta


def _check_content_type(file: UploadFile) -> None:
    ct = (file.content_type or "").lower()
    name = (file.filename or "").lower()
    if ct in _ALLOWED_CT or name.endswith(_ALLOWED_EXT):
        return
    raise unsupported_media("仅支持 PDF/Word/Excel")


def _read_bounded(file: UploadFile, max_bytes: int) -> bytes:
    """有界读:超上限即 413(读 max+1 字节判定,不无界入内存)。"""
    data = file.file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise payload_too_large("上传超过大小上限")
    return data


def _default_dir() -> str:
    return str(Path(tempfile.gettempdir()) / "audit-query-uploads")
