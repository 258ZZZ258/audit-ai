"""T1:R2 条款级 diff——按 clause_path_norm 对齐 → added/removed/changed(unchanged 不计)。"""

from __future__ import annotations

from query.change.version_diff import ClauseChange, diff_clauses


def _c(path: str, text: str) -> dict:
    return {"clause_path_norm": path, "text": text}


def test_added_removed_changed_unchanged():
    old = [_c("第一条", "A"), _c("第二条", "B"), _c("第三条", "C旧")]
    new = [_c("第一条", "A"), _c("第三条", "C新"), _c("第四条", "D")]
    by = {c.clause_path_norm: c for c in diff_clauses(old, new)}
    assert "第一条" not in by  # unchanged 不计
    assert by["第二条"].kind == "removed" and by["第二条"].old_text == "B"
    assert by["第三条"].kind == "changed"
    assert by["第三条"].old_text == "C旧" and by["第三条"].new_text == "C新"
    assert by["第四条"].kind == "added" and by["第四条"].new_text == "D"


def test_empty_sides():
    assert diff_clauses([], [_c("第一条", "X")]) == [ClauseChange("第一条", "added", None, "X")]
    assert diff_clauses([_c("第一条", "X")], []) == [ClauseChange("第一条", "removed", "X", None)]
    assert diff_clauses([], []) == []


def test_dedup_same_path_takes_first():
    old = [_c("第一条", "X1"), _c("第一条", "X2")]  # 同 path 取首条 X1
    new = [_c("第一条", "X1")]
    assert diff_clauses(old, new) == []  # X1 == X1 → unchanged


def test_output_sorted_deterministic():
    # 输出按 clause_path_norm 字符串序(确定性);数字序属后续 polish,此处只验确定性
    paths = ["第三条", "第一条", "第二条"]
    changes = diff_clauses([], [_c(p, "x") for p in paths])
    assert [c.clause_path_norm for c in changes] == sorted(paths)
