"""R6-T2(单元):防注入参数化 SQL——白名单列 + bound params;恶意输入不进 SQL 结构。零栈零模型。"""

from __future__ import annotations

import pytest
from sqlalchemy.dialects import postgresql

from query.stats.dimensions import GroupBy, StatSpec, extract_stat_spec
from query.stats.sql_builder import build_select


def _compiled(spec):
    return build_select(spec).compile(dialect=postgresql.dialect())


def test_aggregate_count_by_category():
    sql = str(_compiled(StatSpec("aggregate", GroupBy.CATEGORY, "count"))).lower()
    assert "violation_category" in sql           # 白名单列
    assert "group by" in sql and "count(" in sql and "order by" in sql


def test_aggregate_sum_amount_by_org():
    sql = str(_compiled(StatSpec("aggregate", GroupBy.ORG, "sum_amount"))).lower()
    assert "penalty_org" in sql and "sum(" in sql and "amount_wan" in sql


def test_aggregate_by_year_extract():
    sql = str(_compiled(StatSpec("aggregate", GroupBy.YEAR, "count"))).lower()
    assert "extract" in sql and "penalty_date" in sql


def test_year_filter_is_bound_param():
    c = _compiled(StatSpec("aggregate", GroupBy.CATEGORY, "count", year_from=2024))
    assert 2024 in c.params.values()             # 值走 bound params
    assert "2024" not in str(c)                  # SQL 结构里无字面 2024


def test_list_mode_filter_order_limit():
    sql = str(_compiled(StatSpec("list", year_from=2024))).lower()
    assert "order by" in sql and "penalty_date" in sql and "limit" in sql


def test_malicious_query_does_not_inject():
    # 恶意问句经规则抽取 → 落默认枚举,绝不进 SQL 结构
    sql = str(_compiled(extract_stat_spec("'; DROP TABLE cases;--"))).lower()
    assert "drop" not in sql and "--" not in sql
    assert "violation_category" in sql           # 落默认 CATEGORY 聚合


def test_org_like_value_is_parameterized():
    evil = "'; DROP TABLE cases;--"
    c = _compiled(StatSpec("list", org_like=evil))
    assert any(evil in str(v) for v in c.params.values())   # 进 params(绑定)
    assert "drop table" not in str(c).lower()               # 不进 SQL 结构


def test_group_col_only_from_whitelist():
    # group_by 只接受 GroupBy 枚举;sql_builder 不从用户串取列(防注入)
    with pytest.raises((KeyError, TypeError, ValueError)):
        build_select(StatSpec("aggregate", group_by="violation_category; DROP", metric="count"))
