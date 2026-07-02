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
    _check_declared_type(file)          # 415 快速拒(声明类型 或 通用+扩展名)
    max_bytes = getattr(svc.qcfg, "max_upload_bytes", _DEFAULT_MAX)
    data = _read_bounded(file, max_bytes)
    _verify_content(file, data)         # 415:通用 content-type 时按魔数校验(防扩展名绕过,F4)
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


#: 通用/未知 content-type:浏览器常对合法文件误标 → 暂放行,但读后按魔数校验(F4 不信任扩展名)。
_GENERIC_CT = {"application/octet-stream", "binary/octet-stream", ""}
#: 文件魔数:PDF(%PDF)/ OOXML zip(docx/xlsx)/ OLE2(旧 doc/xls)。
_MAGIC = (b"%PDF", b"PK\x03\x04", b"\xd0\xcf\x11\xe0")


def _check_declared_type(file: UploadFile) -> None:
    """读前快速判:声明类型在白名单 → 直放;通用类型 + 允许扩展名 → 暂放(读后魔数校验);否则 415。"""
    ct = (file.content_type or "").lower()
    name = (file.filename or "").lower()
    if ct in _ALLOWED_CT:
        return
    if ct in _GENERIC_CT and name.endswith(_ALLOWED_EXT):
        return
    raise unsupported_media("仅支持 PDF/Word/Excel")


def _verify_content(file: UploadFile, data: bytes) -> None:
    """**所有路径按魔数校验**(F7:content-type 客户端可控,声明白名单类型也不单信)。

    5 类允许格式魔数齐全:PDF=%PDF、docx/xlsx=OOXML zip、旧 doc/xls=OLE2。真文件必匹配其一。
    """
    if not any(data.startswith(m) for m in _MAGIC):
        raise unsupported_media("文件内容与类型不符(魔数校验失败)")


def _read_bounded(file: UploadFile, max_bytes: int) -> bytes:
    """有界读:超上限即 413(读 max+1 字节判定,不无界入内存)。"""
    data = file.file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise payload_too_large("上传超过大小上限")
    return data


def _default_dir() -> str:
    return str(Path(tempfile.gettempdir()) / "audit-query-uploads")
