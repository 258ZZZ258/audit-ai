"""§6.6 规则维度抽取(纯函数,零 LLM):统计问句 → ``StatSpec``。

MVP 规则版(同 classify/router 的零-LLM 路径);LLM 识别维度是可选增强、留后续。维度只落**白名单枚举**
``GroupBy``(供 sql_builder 映射到真实 Column,防注入),用户串绝不直接进 SQL。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

#: 年份过滤 regex(20xx 年)
_YEAR = re.compile(r"(20\d{2})\s*年")
#: "X 年以来/起/至今" → year_from(否则 year_eq)
_FROM_HINTS = ("以来", "以后", "起", "至今")

#: 聚合意图词(命中即 aggregate;优先于列表词)
_AGG_KW = (
    "高发", "排名", "占比", "多少起", "多少件", "几起", "数量分布", "分布",
    "逐年", "统计", "最多", "总额", "汇总",
)
#: 列表意图词(无聚合词时 → list)
_LIST_KW = ("有哪些", "列出", "列表")
#: 金额聚合词 → sum_amount(否则 count)
_SUM_KW = ("金额", "罚款", "罚没", "总额")


class GroupBy(StrEnum):
    """聚合维度白名单(值=`cases` 列名 / 派生键;sql_builder 映射到真实 Column)。"""

    CATEGORY = "violation_category"   # 事由 / 板块(L2,默认空)
    ORG = "penalty_org"               # 处罚机构(L1)
    RESPONDENT_TYPE = "respondent_type"  # 对象类型:机构 | 个人(L1)
    YEAR = "year"                     # penalty_date 年(L1,派生)


#: group_by 关键词(按序匹配:RESPONDENT_TYPE 的"对象类型"先于 ORG 的"机构",避免误吞)
_GROUP_RULES: tuple[tuple[tuple[str, ...], GroupBy], ...] = (
    (("对象类型", "个人还是机构", "机构还是个人", "按对象"), GroupBy.RESPONDENT_TYPE),
    (("逐年", "年度", "按年", "每年", "哪一年"), GroupBy.YEAR),
    (("机构", "哪个局", "各局", "按机构"), GroupBy.ORG),
    (("板块", "事由", "违规类型", "违规事由"), GroupBy.CATEGORY),
)


@dataclass(frozen=True)
class StatSpec:
    """统计查询规格(供 sql_builder 构造参数化 SQL)。维度=枚举、过滤值=标量,均非用户串拼接。"""

    mode: str                          # aggregate | list
    group_by: GroupBy | None = None    # 聚合维度(aggregate 必有;list 为 None)
    metric: str = "count"              # count | sum_amount
    year_from: int | None = None       # 过滤:年 >=
    year_eq: int | None = None         # 过滤:年 ==
    org_like: str | None = None        # 过滤:机构含(MVP 不从 NL 抽,留 sql_builder 支持)


def _detect_group_by(q: str) -> GroupBy:
    for kws, dim in _GROUP_RULES:
        if any(k in q for k in kws):
            return dim
    return GroupBy.CATEGORY  # 聚合无显式维度 → 事由(§6.6 主例)


def _detect_years(q: str) -> tuple[int | None, int | None]:
    m = _YEAR.search(q)
    if not m:
        return None, None
    year = int(m.group(1))
    if any(h in q for h in _FROM_HINTS):
        return year, None   # year_from
    return None, year       # year_eq


def extract_stat_spec(query: str) -> StatSpec:
    """统计问句 → ``StatSpec``(规则)。歧义(无聚合词无列表词)默认 aggregate(Q8)。"""
    q = query.strip()
    year_from, year_eq = _detect_years(q)
    # mode:聚合词优先;否则列表词→list;否则默认 aggregate
    if any(k in q for k in _AGG_KW) or not any(k in q for k in _LIST_KW):
        mode = "aggregate"
    else:
        mode = "list"

    if mode == "list":
        return StatSpec(mode="list", year_from=year_from, year_eq=year_eq)
    metric = "sum_amount" if any(k in q for k in _SUM_KW) else "count"
    return StatSpec(
        mode="aggregate",
        group_by=_detect_group_by(q),
        metric=metric,
        year_from=year_from,
        year_eq=year_eq,
    )
