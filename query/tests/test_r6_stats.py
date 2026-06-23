"""R6-T3(单元):编排 + 组表——聚合/列表 TABLE、CATEGORY 全 NULL 明示、空明示。零栈零模型。

fake pg:``session().execute(stmt).all()`` 返回预置 rows(忽略真实 SQL,只验组表逻辑)。
"""

from __future__ import annotations

import json
from datetime import date

from query.contract import BlockType, RouteType
from query.stats.r6_stats import answer_stats


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, _stmt):
        return _FakeResult(self._rows)


class _FakePg:
    def __init__(self, rows):
        self._rows = rows

    def session(self):
        return _FakeSession(self._rows)


def _content(res):
    return json.loads(res.answer_blocks[0].content)


def test_aggregate_table_block():
    res = answer_stats("哪些板块处罚高发", _FakePg([("违规招揽", 5), ("内幕交易", 3)]))
    assert res.route_type is RouteType.STATISTICAL
    assert res.answer_blocks[0].type is BlockType.TABLE
    assert res.answer_blocks[0].stream is False
    d = _content(res)
    assert d["columns"] == ["违规事由", "案件数"]
    assert d["rows"][0] == ["违规招揽", 5]
    assert res.citations == []   # 聚合非条款级


def test_empty_result_explicit():
    res = answer_stats("哪些板块处罚高发", _FakePg([]))
    assert res.answer_blocks[0].type is BlockType.TEXT
    assert "未检索到" in res.answer_blocks[0].content   # 明示、不臆造


def test_category_all_null_consumed_when_present():
    # violation_category 全 NULL(L2 默认空)→ 单行 (None, N) + note
    d = _content(answer_stats("哪些板块处罚高发", _FakePg([(None, 8)])))
    assert d["rows"][0][0] == "（未标注）"
    assert "未标注" in d["note"]


def test_sum_amount_columns():
    d = _content(answer_stats("各机构罚款总额排名", _FakePg([("北京证监局", 120.0)])))
    assert d["columns"] == ["处罚机构", "罚没金额(万元)"]


def test_list_mode_table_date_iso():
    pg = _FakePg([("DV1", "某决定书", "北京证监局", date(2024, 3, 1), "机构", "罚款")])
    d = _content(answer_stats("2024年以来处罚有哪些", pg))
    assert d["columns"][0] == "文书ID" and "标题" in d["columns"]
    assert d["rows"][0][3] == "2024-03-01"   # date → ISO
