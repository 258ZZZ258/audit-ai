"""§6.6 参数化 SQL 构造(防注入核心,纯函数)。

红线:聚合/过滤列**只来自 `GroupBy` 白名单 → 真实 Column**;过滤值经 SQLAlchemy 算子**自动绑定为
bound params**;用户问句只经 `dimensions` 规则映射到枚举/标量,**绝不拼接进 SQL**(SPEC-R6 §7 Never)。

**可见性**(对齐查询侧 `status=effective` 强过滤):`cases` 在 S4 即 upsert,文档可能尚未 INDEXED
(META_REVIEW)或为旧版/未上线;故所有 R6 查询统一 join `doc_versions`,只统计
``pipeline_status==INDEXED`` ∧ ``version_status==effective`` 的可见案例(SPEC §7 / RTM §2-status)。
"""

from __future__ import annotations

from sqlalchemy import Integer, Select, cast, extract, func, select

from common.pg_models import Case, DocVersion
from query.stats.dimensions import GroupBy, StatSpec

#: ⚠ 列表型下钻上限
_LIST_CAP = 50

#: group_by 白名单:枚举 → 真实 Column / 派生表达式(**绝不接受用户串**)
#: YEAR cast 成 Integer——PG ``EXTRACT`` 返 ``Decimal``,不 cast 则 ``json.dumps`` 抛 TypeError。
_GROUP_COL = {
    GroupBy.CATEGORY: Case.violation_category,
    GroupBy.ORG: Case.penalty_org,
    GroupBy.RESPONDENT_TYPE: Case.respondent_type,
    GroupBy.YEAR: cast(extract("year", Case.penalty_date), Integer),
}


def _visibility_conds() -> list:
    """只统计可见案例:INDEXED + effective(对齐查询侧默认过滤)。"""
    return [
        DocVersion.pipeline_status == "INDEXED",
        DocVersion.version_status == "effective",
    ]


def _filters(spec: StatSpec) -> list:
    """可见性 + 维度过滤;值全经算子绑定为 bound params(年/机构含)。"""
    conds = _visibility_conds()
    if spec.year_from is not None:
        conds.append(extract("year", Case.penalty_date) >= spec.year_from)
    if spec.year_eq is not None:
        conds.append(extract("year", Case.penalty_date) == spec.year_eq)
    if spec.org_like:
        conds.append(Case.penalty_org.like(f"%{spec.org_like}%"))  # 整 pattern 作 bound param
    return conds


def build_select(spec: StatSpec) -> Select:
    """``StatSpec`` → SQLAlchemy ``Select``(白名单列 + bound params + 可见性 join)。

    list:cases 卡片列(join doc_versions 取标题 + 可见性)按 ``penalty_date`` 降序取 ``_LIST_CAP``。
    aggregate:白名单维度 GROUP BY + count / sum(amount_wan) 降序(join doc_versions 仅作可见性过滤)。
    """
    conds = _filters(spec)
    join_on = Case.doc_version_id == DocVersion.doc_version_id
    if spec.mode == "list":
        return (
            select(
                Case.doc_version_id,
                DocVersion.title,
                Case.penalty_org,
                Case.penalty_date,
                Case.respondent_type,
                Case.penalty_type,
            )
            .join(DocVersion, join_on)
            .where(*conds)
            .order_by(Case.penalty_date.desc())
            .limit(_LIST_CAP)
        )

    group_col = _GROUP_COL[spec.group_by]  # 非白名单枚举 → KeyError(防注入)
    metric = func.sum(Case.amount_wan) if spec.metric == "sum_amount" else func.count()
    return (
        select(group_col.label("key"), metric.label("value"))
        .join(DocVersion, join_on)
        .where(*conds)
        .group_by(group_col)
        .order_by(metric.desc())
    )
