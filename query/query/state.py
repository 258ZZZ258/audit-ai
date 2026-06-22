"""LangGraph 共享状态 ``QueryState``(PLAN §2.5-2):骨架阶段**一次定全**,加节点永不改状态契约。

字段容纳完整设计所需(N0 多轮 / N1·N3 改写 / N2 场景 / N4 路由 / 检索 / §8 拒答 / §9.2 复核 /
§10 契约)。本切片只填其中一部分(R1 + 拒答 + 路由),其余留默认占位——R2–R6/HyDE/案例桥接/
多模型复核二次开发时只挂节点 + 填字段,不动本契约。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from query.contract import QueryResult


@dataclass
class QueryState:
    query: str                                                # 原始问句
    history: list[dict] = field(default_factory=list)         # 多轮上下文(N0,本切片占位)
    rewrites: list[str] = field(default_factory=list)         # HyDE/分解产物(N1/N3,占位)
    scene: dict | None = None                                 # N2 场景/涉及事项/entity_type
    route_type: str | None = None                             # N4 八路判定(RouteType.value)
    candidates: list[dict] = field(default_factory=list)      # 检索/重排候选(带 clause_id)
    exhausted_scope: list[str] = field(default_factory=list)  # §8 已穷尽事项分区
    citations: list[dict] = field(default_factory=list)       # 四级锚点(PG 回查中间态)
    review: dict | None = None                                # §9.2 多模型复核结果(占位)
    answer_blocks: list[dict] = field(default_factory=list)   # §10 契约 answer_blocks
    result: QueryResult | None = None                         # 终端节点产出的 §10 契约对象
