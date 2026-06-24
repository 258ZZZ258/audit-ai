"""R6-T1(单元):规则维度抽取——mode / group_by / metric / 年过滤 各分支。零栈零模型。"""

from __future__ import annotations

from query.stats.dimensions import GroupBy, StatSpec, extract_stat_spec


def test_aggregate_default_category():
    s = extract_stat_spec("哪些板块处罚高发")
    assert isinstance(s, StatSpec)
    assert s.mode == "aggregate"
    assert s.group_by is GroupBy.CATEGORY   # 板块 / 默认 → 事由
    assert s.metric == "count"


def test_aggregate_by_org():
    s = extract_stat_spec("哪个机构处罚最多")
    assert s.mode == "aggregate" and s.group_by is GroupBy.ORG


def test_aggregate_by_year():
    s = extract_stat_spec("逐年处罚数量分布")
    assert s.mode == "aggregate" and s.group_by is GroupBy.YEAR


def test_respondent_type_dimension():
    s = extract_stat_spec("处罚对象类型分布")
    assert s.group_by is GroupBy.RESPONDENT_TYPE   # 对象类型优先于 ORG 的"机构"


def test_list_mode_with_year_from():
    s = extract_stat_spec("2024年以来的处罚有哪些")
    assert s.mode == "list"
    assert s.year_from == 2024 and s.year_eq is None


def test_ambiguous_defaults_aggregate():
    # 无聚合词无列表词 → 默认聚合(Q8),默认维度 CATEGORY
    s = extract_stat_spec("期货监管处罚情况")
    assert s.mode == "aggregate" and s.group_by is GroupBy.CATEGORY


def test_metric_sum_amount():
    s = extract_stat_spec("各机构罚款总额排名")
    assert s.metric == "sum_amount" and s.group_by is GroupBy.ORG


def test_year_eq_filter():
    s = extract_stat_spec("2023年各板块处罚高发")
    assert s.year_eq == 2023 and s.year_from is None


def test_aggregate_kw_beats_list_kw():
    # "哪些…高发":聚合词优先于"有哪些/哪些"列表意图
    assert extract_stat_spec("哪些板块处罚高发").mode == "aggregate"


def test_count_metric_not_triggered_by_处罚():
    # "处罚"不含"罚款/金额/罚没/总额" → 仍 count(不误判 sum)
    assert extract_stat_spec("哪些板块处罚高发").metric == "count"
