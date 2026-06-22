"""R2 条款级 diff(§6.2 变更内容):按 ``clause_path_norm`` 对齐两版本条款。纯函数、零 LLM。

仅到**条款级**:两侧 text 不等=changed、仅新=added、仅旧=removed、相等不计(字句级 diff 后续)。
入参元素为含 ``clause_path_norm`` / ``text`` 的对象或 dict(由 ``r2_change.fetch_clause_chunks``
提供,``clause_path_norm`` 非空)。同 ``clause_path_norm`` 取首条;输出按 path 字符串序(确定性)。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ClauseChange:
    clause_path_norm: str
    kind: str  # added | removed | changed
    old_text: str | None
    new_text: str | None


def _key(x) -> str:
    return x["clause_path_norm"] if isinstance(x, dict) else x.clause_path_norm


def _text(x) -> str:
    return (x["text"] if isinstance(x, dict) else x.text) or ""


def diff_clauses(old: list, new: list) -> list[ClauseChange]:
    """对齐 → 变更项(added/removed/changed),按 clause_path_norm 排序、同 path 取首条。"""
    old_map: dict[str, str] = {}
    for o in old:
        old_map.setdefault(_key(o), _text(o))
    new_map: dict[str, str] = {}
    for n in new:
        new_map.setdefault(_key(n), _text(n))

    changes: list[ClauseChange] = []
    for path in sorted(set(old_map) | set(new_map)):
        in_old, in_new = path in old_map, path in new_map
        if in_old and in_new:
            if old_map[path] != new_map[path]:
                changes.append(ClauseChange(path, "changed", old_map[path], new_map[path]))
        elif in_new:
            changes.append(ClauseChange(path, "added", None, new_map[path]))
        else:
            changes.append(ClauseChange(path, "removed", old_map[path], None))
    return changes
