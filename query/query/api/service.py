"""T4(SPEC-API §15):域装配。

``QueryService`` 持 ``QueryAgent``/``PgIO``/``SessionStore``/``Retriever``/qcfg,惰性 ``from_config``
(连真栈)或注入(测试)。路由经 ``get_service`` 依赖取它,只调域函数——不进 graph 节点。
"""

from __future__ import annotations

from fastapi import Request


class QueryService:
    """API 域装配门面。共享一套 retriever/pg(问答 + 结构化装配 + 会话共用)。"""

    def __init__(self, *, agent, pg, store, retriever, qcfg) -> None:
        self.agent = agent
        self.pg = pg
        self.store = store
        self.retriever = retriever
        self.qcfg = qcfg

    @classmethod
    def from_config(cls) -> QueryService:
        """连真栈(生产):惰性建;共享 retriever/pg 给 QueryAgent(不重复建)。"""
        from pipeline.config import load_config
        from pipeline.index.pg_io import PgIO
        from query.config import load_query_config
        from query.graph import QueryAgent
        from query.llm import make_llm_client
        from query.observe import make_tracer
        from query.retrieve.hybrid import Retriever
        from query.session.store import SessionStore

        qcfg = load_query_config()
        pg = PgIO.from_config(load_config())
        tracer = make_tracer(qcfg)
        retriever = Retriever.from_config(qcfg, tracer=tracer)
        agent = QueryAgent(retriever, pg, make_llm_client(qcfg), qcfg, tracer=tracer)
        return cls(agent=agent, pg=pg, store=SessionStore(pg), retriever=retriever, qcfg=qcfg)


def get_service(request: Request) -> QueryService:
    """FastAPI 依赖:取(或惰性建)``QueryService``。测试注入 fake 时直接返回。"""
    svc = getattr(request.app.state, "service", None)
    if svc is None:
        svc = QueryService.from_config()
        request.app.state.service = svc
    return svc
