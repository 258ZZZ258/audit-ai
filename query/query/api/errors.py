"""T4(SPEC-API §9):统一错误语义。

单一错误体 ``{"error": {"code", "message", "details?}}`` + 一致状态码;所有异常(自定义 ApiError /
FastAPI 校验 / HTTP / 未处理)都渲染成同一形状。500 **不泄内部细节**(详情进日志/trace)。
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

# 状态码 → 机器可读 code(SPEC-API §9)
_STATUS_CODE = {
    400: "MALFORMED_REQUEST",
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
}


class ApiError(Exception):
    """API 边界异常:携带 HTTP 状态 + 机器可读 code + 人读 message + 可选 details。"""

    def __init__(self, status: int, code: str, message: str, details=None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details


# ── 便捷构造(SPEC-API §9 状态码表)──────────────────────────────────────────
def bad_request(message: str, details=None) -> ApiError:
    return ApiError(400, "MALFORMED_REQUEST", message, details)


def unauthenticated(message: str = "未认证") -> ApiError:
    return ApiError(401, "UNAUTHENTICATED", message)


def forbidden(message: str = "无权限") -> ApiError:
    return ApiError(403, "FORBIDDEN", message)


def not_found(message: str = "资源不存在", details=None) -> ApiError:
    return ApiError(404, "NOT_FOUND", message, details)


def payload_too_large(message: str = "请求体超过大小上限") -> ApiError:
    return ApiError(413, "PAYLOAD_TOO_LARGE", message)


def unsupported_media(message: str = "不支持的文件类型") -> ApiError:
    return ApiError(415, "UNSUPPORTED_MEDIA_TYPE", message)


def validation_error(message: str, details=None) -> ApiError:
    return ApiError(422, "VALIDATION_ERROR", message, details)


def _body(code: str, message: str, details=None) -> dict:
    err: dict = {"code": code, "message": message}
    if details is not None:
        err["details"] = details
    return {"error": err}


def install_error_handlers(app: FastAPI) -> None:
    """注册统一异常处理器:自定义 / 校验 / HTTP / 未处理 → 同一错误体。"""

    @app.exception_handler(ApiError)
    async def _on_api_error(_request: Request, exc: ApiError):
        return JSONResponse(
            status_code=exc.status, content=_body(exc.code, exc.message, exc.details)
        )

    @app.exception_handler(RequestValidationError)
    async def _on_validation(_request: Request, exc: RequestValidationError):
        details = jsonable_encoder(exc.errors())
        return JSONResponse(
            status_code=422, content=_body("VALIDATION_ERROR", "请求参数校验失败", details)
        )

    @app.exception_handler(StarletteHTTPException)
    async def _on_http(_request: Request, exc: StarletteHTTPException):
        code = _STATUS_CODE.get(exc.status_code, "ERROR")
        return JSONResponse(status_code=exc.status_code, content=_body(code, str(exc.detail)))

    @app.exception_handler(Exception)
    async def _on_unhandled(_request: Request, _exc: Exception):
        # 500 不泄内部细节(堆栈/message 进日志/trace,不回客户端)
        return JSONResponse(status_code=500, content=_body("INTERNAL_ERROR", "内部错误"))
