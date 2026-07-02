"""T9(SPEC-API §8.1):导出查询报告端点。

``POST /conversations/{cid}/messages/{mid}/export`` {format:"xlsx"}:过导出权限点(stub/无权 403)→
从消息 result_json 填 xlsx 模板(含 AI 标识页脚)→ 文件流。默认且本轮唯一格式 xlsx。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from query.api.auth import Principal, current_principal, require_export_permission
from query.api.errors import not_found
from query.api.export_xlsx import build_export_xlsx
from query.api.service import QueryService, get_service

router = APIRouter(prefix="/conversations", tags=["export"])

_XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class ExportBody(BaseModel):
    format: Literal["xlsx"] = "xlsx"   # 本轮唯一;非 xlsx → 422


@router.post("/{cid}/messages/{mid}/export")
def export(
    cid: str, mid: str,
    body: ExportBody | None = None,
    svc: QueryService = Depends(get_service),
    principal: Principal = Depends(current_principal),
) -> Response:
    require_export_permission(principal)   # 无权 → 403(+ 操作日志位)
    msg = svc.store.get_message(mid)
    if msg is None or msg.get("conversation_id") != cid:
        raise not_found("消息不存在")
    conv = svc.store.get_conversation(cid)
    data = build_export_xlsx(
        question=_question_for(conv, msg.get("seq", 0)),
        answer_summary=msg.get("content"),
        result=msg.get("result_json"),
        exporter=principal.user_id,
        exported_at=datetime.now().isoformat(timespec="seconds"),
    )
    filename = f"query_report_{mid}.xlsx"
    return Response(
        content=data, media_type=_XLSX_MEDIA,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _question_for(conv, assistant_seq):
    """配对用户问句 = seq 紧邻本条 assistant 之前的最后一条 user。"""
    if not conv:
        return None
    prev = [
        m for m in conv.get("messages", [])
        if m.get("role") == "user" and m.get("seq", 0) < assistant_seq
    ]
    return prev[-1]["content"] if prev else None
