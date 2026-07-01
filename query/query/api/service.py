"""T4(SPEC-API §15):域装配。

``QueryService`` 持 ``QueryAgent``/``PgIO``/``SessionStore``/``Retriever``/qcfg,惰性 ``from_config``
(连真栈)或注入(测试)。路由经 ``get_service`` 依赖取它,只调域函数——不进 graph 节点。
"""

from __future__ import annotations

from fastapi import Request


class QueryService:
    """API 域装配门面。共享一套 retriever/pg(问答 + 结构化装配 + 会话共用)。"""

    def __init__(self, *, agent, pg, store, retriever, qcfg, llm=None) -> None:
        self.agent = agent
        self.pg = pg
        self.store = store
        self.retriever = retriever
        self.qcfg = qcfg
        self.llm = llm            # 主答 LLM(SSE 真流式 generate_evidence_stream 用)
        self.uploads: dict = {}   # upload_id → meta(只存不消费;附件引用校验用,SPEC-API §8.4)

    def structured_for(self, query, *, include_superseded=False, corpus=None):
        """检索 + PG 回查 + 装配 → ``StructuredResult``(四-Tab)。

        与 ``agent.ask`` 各检索一次(PLAN 接受的双检索;确定性 → 同候选)。``corpus`` 限内规/外规。
        """
        from query.api.structured import assemble_structured, fetch_pg_context
        from query.retrieve.hybrid import drop_degraded

        cands = drop_degraded(
            self.retriever.retrieve(query, include_superseded=include_superseded)
        )
        cands = _filter_corpus(cands, corpus)
        case_cands = (
            drop_degraded(self.retriever.retrieve_cases(query))
            if getattr(self.qcfg, "attach_cases", False) else []
        )
        chunk_doc, case_rows = fetch_pg_context(self.pg, cands, case_cands)
        return assemble_structured(cands, case_cands, chunk_doc, case_rows)

    def clause_detail(self, clause_id):
        """条款回查(SPEC-API §8.3):四级锚点 + 全文 + 节级父块。不存在 → None。

        权威 PG(``anchors``/``chunks.text``,非 Milvus 截断);「查看原文/详细释义/完整定义」都打它。
        """
        from common.pg_models import Chunk
        from query.generate.anchors import fetch_anchors, fetch_parent_text

        cit = fetch_anchors(self.pg, [clause_id]).get(clause_id)
        if cit is None:
            return None
        with self.pg.session() as s:
            chunk = s.get(Chunk, clause_id)
            text = chunk.text if chunk is not None else None
        detail = cit.to_dict()
        detail["text"] = text
        detail["parent_text"] = fetch_parent_text(self.pg, clause_id)
        return detail

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
        llm = make_llm_client(qcfg)
        agent = QueryAgent(retriever, pg, llm, qcfg, tracer=tracer)
        return cls(
            agent=agent, pg=pg, store=SessionStore(pg), retriever=retriever, qcfg=qcfg, llm=llm,
        )


_CORPUS_MAP = {"internal": "P-INT", "external": "P-EXT"}


def _filter_corpus(cands, corpus):
    """按 corpus 限定候选(internal→P-INT / external→P-EXT);None → 全留。"""
    if not corpus:
        return cands
    ct = _CORPUS_MAP[corpus]
    return [c for c in cands if c.corpus_type == ct]


def get_service(request: Request) -> QueryService:
    """FastAPI 依赖:取(或惰性建)``QueryService``。测试注入 fake 时直接返回。"""
    svc = getattr(request.app.state, "service", None)
    if svc is None:
        svc = QueryService.from_config()
        request.app.state.service = svc
    return svc
