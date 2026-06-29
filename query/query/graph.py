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
from query.llm import LLMClient, maybe_make_llm_client
from query.observe import make_tracer
from query.refuse.coverage_refusal import refuse_coverage, refuse_out_of_domain
from query.retrieve.sufficiency import assess
from query.state import QueryState
from query.understand.classify import SceneType, classify
from query.understand.merge import merge_context
from query.understand.router import route

# route_type → 终端节点名(R4/R5 收敛到 placeholder)
_TERMINAL = {
    RouteType.EVIDENCE: "evidence",
    RouteType.CLARIFY: "clarify",
    RouteType.REFUSE: "refuse",
    RouteType.CHANGE: "change",
    RouteType.CASE: "r3_case",
    RouteType.STATISTICAL: "r6_stats",
    RouteType.ENUMERATE: "r4_listing",
    RouteType.JUDGMENTAL: "r5_judgment",
}
# 八路全实装(R5 收官)→ 无占位路由;``_placeholder`` 节点保留为**防御兜底**(未知 route_type 仍落它)。
_PLACEHOLDER_NOTE: dict = {}

# 未识别具体业务事项时的确定性兜底,保覆盖拒答 exhausted_scope 非空(SPEC §8.2 可解释契约)。
# ⚠ 临时:N2 未接 dict_biz_domains/dict_entity_types 加载(见 GAP §依赖缺口),接入后即命中真实事项。
_FALLBACK_SCOPE = ["现行制度(未识别具体业务事项)"]


def resolve_scope(matters) -> list[str]:
    """覆盖拒答的 exhausted_scope 必非空(可解释)。识别到事项用之,否则确定性兜底。"""
    return list(dict.fromkeys(matters)) or list(_FALLBACK_SCOPE)


class QueryAgent:
    """编排门面:持检索 / PG / LLM 依赖,编译一次 LangGraph,``ask`` 跑一次问答。"""

    def __init__(self, retriever, pg, llm: LLMClient, qcfg, tracer=None) -> None:
        self._retriever = retriever
        self._pg = pg
        self._llm = llm
        self._qcfg = qcfg
        # §9.3 观测 tracer(只读旁路):默认 make_tracer(observe 关 → NoopTracer 零网络)
        self._tracer = tracer or make_tracer(qcfg)
        # N0 归并客户端:仅 merge_context 开 + gateway + 有 key 时建(真 LLM 为主);否则 None →
        # merge_context 走规则版(stub/关/无 key → 零网络、不崩溃,QUERY-N0-OFFLINE-GATE)。
        self._merge_llm = maybe_make_llm_client(
            qcfg.merge_context, qcfg, model=qcfg.merge_model or qcfg.llm_model
        )
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
        # §9.3 单一 tracer:传 Retriever(发 HyDE/子查询 event)+ 自身(ask 开 trace)→ 同一条 trace
        tracer = make_tracer(qcfg)
        return cls(Retriever.from_config(qcfg, tracer=tracer), PgIO.from_config(load_config()),
                   make_llm_client(qcfg), qcfg, tracer=tracer)

    # ── 节点(纯函数薄封装;只 evidence 触碰检索/PG/LLM)──────────────────────
    def _n0_merge(self, state: QueryState) -> dict:
        """N0 多轮上下文归并(§3.4):指代消解/省略补全为自足问句。空 history → no-op。

        gateway 时真 LLM 为主(`_merge_llm`),stub/关 → 规则版;LLM 失败 fail-safe 回落(见
        `merge_context`)。仅改写时写回 `query`(归并后下游 `understand`/检索读它,零改);未变 → `{}`
        (单轮 byte 等价)。R7 澄清闭环 = 调用方带 history 重入本节点(跨请求,§6.7/§0.3)。
        """
        merged = merge_context(state.query, state.history, llm=self._merge_llm)
        return {"query": merged} if merged != state.query else {}

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
        from query.retrieve.hybrid import drop_degraded

        # 契约:degraded 块仅全文检索、不参与条款级引用 → R1 充分性与生成只用非降级候选
        cands = drop_degraded(self._retriever.retrieve(state.query))
        matters = (state.scene or {}).get("matters", [])
        scope = resolve_scope(matters)  # exhausted_scope 必非空(可解释拒答)
        suff = assess(cands, matters, min_hits=self._qcfg.sufficiency_min_hits)
        if suff.sufficient:
            res = generate_evidence(state.query, cands, self._pg, self._llm, exhausted_scope=scope)
        else:
            closest = list(fetch_anchors(self._pg, [c.chunk_id for c in cands][:3]).values())
            res = refuse_coverage(scope, closest)
        return {"result": self._maybe_attach_cases(state, res)}

    def _maybe_attach_cases(self, state: QueryState, res: QueryResult) -> QueryResult:
        """§6.3 附挂通道:仅**充分 evidence** 答复、**非概念判断型**附挂;拒答/降级不挂、可关。"""
        if not self._qcfg.attach_cases or res.route_type is not RouteType.EVIDENCE:
            return res  # 关 / 拒答降级 → 不挂
        if (state.scene or {}).get("scene_type") == SceneType.DEFINITION.value:
            return res  # 概念判断型不附挂(§6.3 适用边界)
        from query.case.r3_case import attach_cases  # 懒导入,避免 import 期拉 pipeline

        return attach_cases(res, state.query, res.citations, self._retriever, self._pg, self._qcfg)

    def _change(self, state: QueryState) -> dict:
        from query.change.r2_change import answer_change  # 懒导入,避免 import 期拉 pipeline

        return {"result": answer_change(state.query, self._retriever, self._pg)}

    def _r3_case(self, state: QueryState) -> dict:
        from query.case.r3_case import answer_case  # 懒导入,避免 import 期拉 pipeline

        return {"result": answer_case(state.query, self._retriever, self._pg, self._qcfg)}

    def _r6_stats(self, state: QueryState) -> dict:
        from query.stats.r6_stats import answer_stats  # 懒导入,避免 import 期拉 pipeline

        return {"result": answer_stats(state.query, self._pg)}

    def _r4_listing(self, state: QueryState) -> dict:
        from query.listing.r4_listing import answer_enumerate  # 懒导入,避免 import 期拉 pipeline

        # 复用 N2(classify)已抽取的 matters/entity_types 注入 R4 标量过滤(T6 验收)。dict 未接
        # PG 加载 → scene 抽取为空 → biz/entity 降级、只下推 chunk_type;dict 接入后图路径自动生效。
        scene = state.scene or {}
        return {
            "result": answer_enumerate(
                state.query, self._retriever, self._pg,
                biz_terms=scene.get("matters", ()), entity_terms=scene.get("entity_types", ()),
            )
        }

    def _r5_judgment(self, state: QueryState) -> dict:
        from query.judge.r5_judgment import answer_judgment  # 懒导入,避免 import 期拉 pipeline

        # R5 判定型(§6.5):三段式硬约束 + review_required + 不出裸结论;默认零-LLM(stub)
        return {
            "result": answer_judgment(
                state.query, self._retriever, self._pg, self._llm, self._qcfg
            )
        }

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
        g.add_node("n0_merge", self._n0_merge)
        g.add_node("understand", self._understand)
        g.add_node("evidence", self._evidence)
        g.add_node("change", self._change)
        g.add_node("r3_case", self._r3_case)
        g.add_node("r6_stats", self._r6_stats)
        g.add_node("r4_listing", self._r4_listing)
        g.add_node("r5_judgment", self._r5_judgment)
        g.add_node("clarify", self._clarify)
        g.add_node("refuse", self._refuse)
        g.add_node("placeholder", self._placeholder)
        g.add_edge(START, "n0_merge")        # N0 多轮归并前置(§3 前端节点链)
        g.add_edge("n0_merge", "understand")
        g.add_conditional_edges(
            "understand",
            self._route_edge,
            {"evidence": "evidence", "change": "change", "r3_case": "r3_case",
             "r6_stats": "r6_stats", "r4_listing": "r4_listing", "r5_judgment": "r5_judgment",
             "clarify": "clarify", "refuse": "refuse", "placeholder": "placeholder"},
        )
        for n in ("evidence", "change", "r3_case", "r6_stats", "r4_listing", "r5_judgment",
                  "clarify", "refuse", "placeholder"):
            g.add_edge(n, END)
        return g.compile()

    def ask(self, query: str, history: list[dict] | None = None) -> QueryResult:
        """端到端问答。``history``(多轮对话,N0 归并用)缺省单轮(空 → N0 no-op,byte 等价)。

        §9.3:包一条 trace —— ask 开 trace(set contextvar),Retriever 的 HyDE/子查询 event 挂同一条;
        终态 metadata(归并句/scene/route_type)入 trace。tracer 只读旁路,observe 关 → Noop 零开销。
        """
        with self._tracer.trace("query", input=query) as span:
            final = self._app.invoke(QueryState(query=query, history=history or []))
            result = final["result"]
            span.update(
                output=result.route_type.value,
                metadata={
                    "merged_query": final.get("query"),
                    "scene": final.get("scene"),
                    "route_type": final.get("route_type"),
                },
            )
            return result

    def route_only(self, query: str) -> RouteType:
        """仅路由判定(调试 / `query route`),不触发检索。"""
        return route(query, classify(query)).route_type
