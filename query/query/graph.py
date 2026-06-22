"""LangGraph 装配(§1.2 运行时状态机):router → {R1 evidence / R7 clarify / R8 refuse / R2–R6 占位}。

节点为**纯函数的薄封装**(各 understand/generate/refuse 本身不 import langgraph);graph.py 只装配
节点与条件边——换底座(去 langgraph)纯函数照搬(PLAN §2.5-1)。共享状态 = ``QueryState``(§2.5-2)。
本切片只实装 R1/R7/R8;R2–R6 走**诚实占位**节点(产出正确 route_type + "暂未实装",不裸答、不报错)。
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from query.contract import AnswerBlock, BlockType, QueryResult, RouteType
from query.generate.anchors import fetch_anchors
from query.generate.r1_evidence import generate_evidence
from query.llm import LLMClient
from query.refuse.coverage_refusal import refuse_coverage, refuse_out_of_domain
from query.retrieve.sufficiency import assess
from query.state import QueryState
from query.understand.classify import classify
from query.understand.router import route

# route_type → 终端节点名(R2–R6 收敛到 placeholder)
_TERMINAL = {
    RouteType.EVIDENCE: "evidence",
    RouteType.CLARIFY: "clarify",
    RouteType.REFUSE: "refuse",
    RouteType.CHANGE: "placeholder",
    RouteType.CASE: "placeholder",
    RouteType.ENUMERATE: "placeholder",
    RouteType.JUDGMENTAL: "placeholder",
    RouteType.STATISTICAL: "placeholder",
}
_PLACEHOLDER_NOTE = {
    RouteType.CHANGE: "变更查询(R2)",
    RouteType.CASE: "相似案例(R3)",
    RouteType.ENUMERATE: "多文档列举(R4)",
    RouteType.JUDGMENTAL: "判定型(R5)",
    RouteType.STATISTICAL: "统计型(R6)",
}


class QueryAgent:
    """编排门面:持检索 / PG / LLM 依赖,编译一次 LangGraph,``ask`` 跑一次问答。"""

    def __init__(self, retriever, pg, llm: LLMClient, qcfg) -> None:
        self._retriever = retriever
        self._pg = pg
        self._llm = llm
        self._qcfg = qcfg
        self._app = self._build()

    @classmethod
    def from_config(cls, qcfg=None) -> QueryAgent:
        """连真栈(CLI/生产用):懒导入 pipeline 侧,避免 import 期拉重依赖。"""
        from pipeline.config import load_config
        from pipeline.index.pg_io import PgIO
        from query.config import load_query_config
        from query.llm import make_llm_client
        from query.retrieve.hybrid import Retriever

        qcfg = qcfg or load_query_config()
        return cls(Retriever.from_config(qcfg), PgIO.from_config(load_config()),
                   make_llm_client(qcfg), qcfg)

    # ── 节点(纯函数薄封装;只 evidence 触碰检索/PG/LLM)──────────────────────
    def _understand(self, state: QueryState) -> dict:
        scene = classify(state.query)
        decision = route(state.query, scene)
        return {
            "scene": {
                "scene_type": scene.scene_type.value,
                "matters": scene.matters,
                "entity_types": scene.entity_types,
            },
            "route_type": decision.route_type.value,
        }

    def _route_edge(self, state: QueryState) -> str:
        return _TERMINAL.get(RouteType(state.route_type), "placeholder")

    def _evidence(self, state: QueryState) -> dict:
        cands = self._retriever.retrieve(state.query)
        matters = (state.scene or {}).get("matters", [])
        suff = assess(cands, matters, min_hits=self._qcfg.sufficiency_min_hits)
        if suff.sufficient:
            res = generate_evidence(state.query, cands, self._pg, self._llm)
        else:
            anchors = fetch_anchors(self._pg, [c.chunk_id for c in cands])
            res = refuse_coverage(suff.exhausted_scope, list(anchors.values()))
        return {"result": res}

    def _clarify(self, state: QueryState) -> dict:
        blk = AnswerBlock(
            BlockType.CLARIFY_QUESTION,
            "请补充关键信息(如具体制度名称、业务场景或时间范围)以便精确检索。",
        )
        return {"result": QueryResult(RouteType.CLARIFY, answer_blocks=[blk], confidence=0.0)}

    def _refuse(self, state: QueryState) -> dict:
        return {"result": refuse_out_of_domain()}

    def _placeholder(self, state: QueryState) -> dict:
        rt = RouteType(state.route_type)
        note = _PLACEHOLDER_NOTE.get(rt, "该问句类型")
        blk = AnswerBlock(
            BlockType.TEXT,
            f"{note}路由已识别,但本期(MVP)暂未实装该路径,不作答以免给出无依据结论。",
        )
        return {"result": QueryResult(rt, answer_blocks=[blk], confidence=0.0)}

    def _build(self):
        g = StateGraph(QueryState)
        g.add_node("understand", self._understand)
        g.add_node("evidence", self._evidence)
        g.add_node("clarify", self._clarify)
        g.add_node("refuse", self._refuse)
        g.add_node("placeholder", self._placeholder)
        g.add_edge(START, "understand")
        g.add_conditional_edges(
            "understand",
            self._route_edge,
            {"evidence": "evidence", "clarify": "clarify",
             "refuse": "refuse", "placeholder": "placeholder"},
        )
        for n in ("evidence", "clarify", "refuse", "placeholder"):
            g.add_edge(n, END)
        return g.compile()

    def ask(self, query: str) -> QueryResult:
        return self._app.invoke(QueryState(query=query))["result"]

    def route_only(self, query: str) -> RouteType:
        """仅路由判定(调试 / `query route`),不触发检索。"""
        return route(query, classify(query)).route_type
