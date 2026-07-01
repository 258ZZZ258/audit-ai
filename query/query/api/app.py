"""T4(SPEC-API §15):FastAPI app 工厂。

薄壳 over ``QueryService``;统一错误处理(§9);``/healthz`` 免依赖(不碰真栈)。业务路由(会话/问答/
条款/推荐/上传/导出/SSE)在 T5–T11 逐个 ``include_router`` 挂载。

启动:``uvicorn 'query.api.app:app' --host 127.0.0.1 --port 8770``(``app`` = ``create_app()``)。
"""

from __future__ import annotations

from fastapi import FastAPI

from query.api import routes_conversations
from query.api.errors import install_error_handlers

_API_PREFIX = "/api/query/v1"


def create_app(service=None) -> FastAPI:
    """建 app。``service`` 注入(测试)存 ``app.state.service``;None → 首请求惰性建。"""
    app = FastAPI(title="制度查询智能体 API", version="0.1.0")
    app.state.service = service
    install_error_handlers(app)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    # 业务路由(T5–T11 逐个挂载,前缀 /api/query/v1)
    app.include_router(routes_conversations.router, prefix=_API_PREFIX)
    return app


#: uvicorn 入口(惰性 service:首请求时连真栈)。
app = create_app()
