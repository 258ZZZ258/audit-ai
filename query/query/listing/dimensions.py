"""§6.4 规则维度抽取(纯函数,零 LLM):列举问句 → ``EnumSpec``。

MVP 规则版(同 classify/router/R6 dimensions 的零-LLM 路径);LLM 识别维度留可选接缝。
``biz_domains`` / ``entity_types`` 经词典子串匹配(``extract_terms``,**只返词典成员**),
用户串绝不直接进 Milvus expr(防注入,见 ``r4_listing.build_milvus_expr``)。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from query.understand.classify import extract_terms

#: 义务意图词(命中 → obligation_only,触发 E1 ``is_obligation`` 后过滤;Q3)。
#: "制度 / 规定 / 哪些" 列举型**不**在此(避免"列出制度"被误缩为只剩义务条款)。
_OBLIGATION_KW = ("要求", "义务", "必须", "应当", "禁止", "不得")


@dataclass(frozen=True)
class EnumSpec:
    """列举查询规格(供 build_milvus_expr 构标量过滤 + 编排选 E1 后过滤)。"""

    chunk_type_pref: bool = True                       # 列举偏好 clause(Q5,硬过滤 clause)
    biz_domains: list[str] = field(default_factory=list)   # E2 涉及事项(词典抽取,空→不过滤)
    entity_types: list[str] = field(default_factory=list)  # E2 实体类型(词典抽取,空→不过滤)
    obligation_only: bool = False                      # E1 义务意图 → is_obligation 后过滤


def extract_enum_spec(
    query: str, *, biz_terms: Iterable[str] = (), entity_terms: Iterable[str] = ()
) -> EnumSpec:
    """列举问句 → ``EnumSpec``(规则)。义务意图触发 obligation_only;biz/entity 走词典子串。"""
    q = query.strip()
    return EnumSpec(
        chunk_type_pref=True,
        biz_domains=extract_terms(q, biz_terms),
        entity_types=extract_terms(q, entity_terms),
        obligation_only=any(k in q for k in _OBLIGATION_KW),
    )
