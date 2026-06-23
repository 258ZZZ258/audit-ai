"""T2(单元):R2 纯部分——修订原因明示(不推测)/ 契约组装 / 无前驱明示。"""

from __future__ import annotations

from types import SimpleNamespace

from query.change.r2_change import build_change_result, build_no_history, format_reason
from query.change.version_diff import ClauseChange
from query.contract import BlockType, Citation, RouteType


def _dv(dvid, issue_date="2024-01-01", status="effective", title="合同管理办法"):
    return SimpleNamespace(
        doc_version_id=dvid, issue_date=issue_date, version_status=status, title=title
    )


def test_format_reason_present_verbatim():
    assert format_reason(SimpleNamespace(raw_text="为对接新规修订")) == "为对接新规修订"


def test_format_reason_absent_explicit_no_speculation():
    assert "未提供" in format_reason(None)
    assert "未提供" in format_reason(SimpleNamespace(raw_text="   "))


def test_build_change_result_shape():
    changes = [
        ClauseChange("第三条", "changed", "旧", "新"),
        ClauseChange("第四条", "added", None, "新增"),
    ]
    res = build_change_result(
        _dv("NEW"), _dv("OLD", title=None), changes, "为对接新规", [Citation(clause_id="c1")]
    )
    assert res.route_type is RouteType.CHANGE
    assert BlockType.TABLE in [b.type for b in res.answer_blocks]
    text = " ".join(b.content for b in res.answer_blocks)
    assert "修改" in text and "新增" in text and "第三条" in text
    assert "为对接新规" in text and "未纳入本期" in text  # 原因 + 背景占位
    assert [c.clause_id for c in res.citations] == ["c1"]


def test_build_no_history_explicit():
    res = build_no_history(_dv("V1"))
    assert res.route_type is RouteType.CHANGE
    assert "无历史版本" in res.answer_blocks[0].content
