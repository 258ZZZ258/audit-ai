"""R2 条款级 diff(§6.2 变更内容):按 ``clause_path_norm`` 对齐两版本条款。纯函数、零 LLM。

仅到**条款级**:两侧 text 不等=changed、仅新=added、仅旧=removed、相等不计(字句级 diff 后续)。
入参元素含 ``clause_path_norm`` / ``text`` / ``seq``(由 ``r2_change.fetch_clause_chunks`` 提供)。
**同 ``clause_path_norm`` 的多子块**(切块器拆超长条款/表格)按 ``seq`` 升序**聚合拼接**后比较——
后续子块差异不漏。输出按 path 字符串序(确定性)。
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


def _seq(x) -> int:
    v = x["seq"] if isinstance(x, dict) else getattr(x, "seq", 0)
    return v if v is not None else 0


def _aggregate(chunks: list) -> dict[str, str]:
    """同 clause_path_norm 的多子块按 seq 升序拼接(覆盖切块器对超长条款/表格的拆分)。"""
    groups: dict[str, list] = {}
    for c in chunks:
        groups.setdefault(_key(c), []).append(c)
    return {
        path: "\n".join(_text(i) for i in sorted(items, key=_seq))
        for path, items in groups.items()
    }


def diff_clauses(old: list, new: list) -> list[ClauseChange]:
    """聚合子块 → 对齐 → 变更项(added/removed/changed),按 clause_path_norm 字符串序输出。"""
    old_map = _aggregate(old)
    new_map = _aggregate(new)

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
