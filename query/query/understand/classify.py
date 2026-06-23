"""N2 查询理解:场景类型(规则)+ 涉及事项 / entity_type(词典子串匹配)。§3.2 / §3.3。

MVP **零 LLM**:场景类型按关键词规则、优先级序(§4.3:判定>统计>变更>案例>列举>定义>依据);
涉及事项 / entity_type 走词典子串匹配(词表由调用方注入:dict_biz_domains / dict_entity_types)。
LLM 辅助分类是可选增强(接 query.llm),非默认路径;规则将来由 dict_intent_routes 替换(§4.1)。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum


class SceneType(StrEnum):
    EVIDENCE = "evidence"        # 依据型(what/where,默认)
    BEHAVIOR = "behavior"        # 行为合规/违规咨询(判定型,§6.5)
    DEFINITION = "definition"    # 概念定义
    ENUMERATE = "enumerate"      # 列举枚举
    CHANGE = "change"            # 变更追溯
    CASE = "case"                # 相似案例
    STATISTICAL = "statistical"  # 统计聚合


# 关键词规则(优先级从高到低,首个命中即定;§4.3 判定>统计>变更>案例>列举>定义>依据)
_BEHAVIOR = (
    "是否违规", "违不违规", "违规吗", "是否合规", "能不能", "能否", "可不可以",
    "可以吗", "需不需要", "算不算", "是否需要", "是否可以",
)
_STATISTICAL = (
    "高发", "统计", "多少起", "多少件", "排名", "占比", "几起", "数量分布",
    # 列表型统计触发(§6.6 例「2024年以来…处罚有哪些」)——区别于 R3"案例"与 R4"制度…规定"列举
    "处罚有哪些", "处罚有什么", "处罚都有哪些",
)
_CHANGE = ("变更", "修订", "旧版", "什么时候改", "何时修订", "修改了", "历次修改")
_CASE = ("类似案例", "类似的处罚", "类似处罚", "有没有案例", "相关案例", "处罚案例", "处罚先例")
_ENUMERATE = ("哪些制度", "列出所有", "列举", "有哪些规定", "哪些规定", "哪些要求", "所有关于")
_DEFINITION = ("什么是", "是什么意思", "的定义", "是否等于", "等于")

_RULES: tuple[tuple[tuple[str, ...], SceneType], ...] = (
    (_BEHAVIOR, SceneType.BEHAVIOR),
    (_STATISTICAL, SceneType.STATISTICAL),
    (_CHANGE, SceneType.CHANGE),
    (_CASE, SceneType.CASE),
    (_ENUMERATE, SceneType.ENUMERATE),
    (_DEFINITION, SceneType.DEFINITION),
)


def classify_scene(query: str) -> SceneType:
    q = query.strip()
    for kws, scene in _RULES:
        if any(k in q for k in kws):
            return scene
    return SceneType.EVIDENCE


def extract_terms(query: str, terms: Iterable[str]) -> list[str]:
    """词典子串匹配(去重保序)。供涉及事项 / entity_type 抽取。"""
    out: list[str] = []
    for t in terms:
        if t and t in query and t not in out:
            out.append(t)
    return out


@dataclass
class Scene:
    scene_type: SceneType
    matters: list[str] = field(default_factory=list)       # 涉及事项(dict_biz_domains)
    entity_types: list[str] = field(default_factory=list)  # 适用实体类型(dict_entity_types)


def classify(
    query: str, *, biz_terms: Iterable[str] = (), entity_terms: Iterable[str] = ()
) -> Scene:
    return Scene(
        scene_type=classify_scene(query),
        matters=extract_terms(query, biz_terms),
        entity_types=extract_terms(query, entity_terms),
    )
