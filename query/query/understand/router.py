"""N4 八路意图路由(§4)。MVP 规则版:场景类型 → route_type + R7 澄清 / R8 兜底。

**八路分满**:R1/R7/R8 由本切片实装下游;R2–R6 产出正确 route_type 但走诚实占位(graph 装配,T13)。
规则与置信度是 MVP 骨架,将来由 dict_intent_routes(真实日志 + 18 问冷启动)训练分类器替换(§4.1)。
"""

from __future__ import annotations

from dataclasses import dataclass

from query.contract import RouteType
from query.understand.classify import Scene, SceneType

# 场景类型 → route_type(§4.2)
_SCENE_TO_ROUTE = {
    SceneType.EVIDENCE: RouteType.EVIDENCE,
    SceneType.BEHAVIOR: RouteType.JUDGMENTAL,
    # 概念定义尽力当依据查询答(辨析类超范围 §0.3,靠拒答/复核兜)
    SceneType.DEFINITION: RouteType.EVIDENCE,
    SceneType.ENUMERATE: RouteType.ENUMERATE,
    SceneType.CHANGE: RouteType.CHANGE,
    SceneType.CASE: RouteType.CASE,
    SceneType.STATISTICAL: RouteType.STATISTICAL,
}

# 明显跑题标记(无领域锚点时触发 R8;dict 化前的 MVP 黑名单)
_OFF_DOMAIN = ("天气", "笑话", "股票", "彩票", "基金推荐", "午饭", "吃什么", "唱歌", "讲个")
# 领域锚点:命中则不判跑题(防误杀)
_DOMAIN_ANCHOR = (
    "制度", "规定", "办法", "条款", "报销", "违规", "合规", "处罚", "义务",
    "备案", "披露", "投顾", "印章", "开户", "审计", "修订", "细则", "指引",
)
# 明显指代 → R7 澄清
_PRONOUN_ONLY = ("它呢", "这个", "那个", "他呢", "这条", "那条", "上面那个", "呢")
_MIN_LEN = 4  # ⚠ 过短即判歧义(MVP 骨架值)


@dataclass
class RouteDecision:
    route_type: RouteType
    confidence: float
    reason: str


def _is_off_domain(q: str) -> bool:
    return any(k in q for k in _OFF_DOMAIN) and not any(a in q for a in _DOMAIN_ANCHOR)


def _is_ambiguous(q: str) -> bool:
    return len(q) < _MIN_LEN or q in _PRONOUN_ONLY


def route(query: str, scene: Scene) -> RouteDecision:
    q = query.strip()
    if _is_off_domain(q):
        return RouteDecision(RouteType.REFUSE, 0.9, "off_domain")
    if _is_ambiguous(q):
        return RouteDecision(RouteType.CLARIFY, 0.5, "ambiguous_or_too_short")
    rt = _SCENE_TO_ROUTE[scene.scene_type]
    conf = 0.6 if scene.scene_type is SceneType.EVIDENCE else 0.85
    return RouteDecision(rt, conf, f"scene={scene.scene_type.value}")
