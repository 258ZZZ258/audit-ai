"""版本关系建模:解析 manifest supersedes 声明 → 关系类型 + 目标(纯逻辑,无 PG)。

demo 编码约定(生产语义见 V1.5,不在 repo):
- 空                              → NONE
- 单文件名                        → REVISE_REPLACE(继承 logical,内容延续)
- ``abolish:<file>`` / ``废止:<file>`` → ABOLISH_ONLY(独立文书,不继承 logical,仅记被废止版)
- 多文件名(``; , ; , 、`` 分隔)  → MERGE(多旧→一新,demo 不支持)
- SPLIT_REPLACE(一旧→多新)       批次级判定:≥2 个新件指向同一旧件(见 ``detect_split_targets``)

支持 = {REVISE_REPLACE, ABOLISH_ONLY};MERGE/SPLIT_REPLACE demo 不支持 → 转人工队列(由 s0 入队)。
原子切换(旧版置 superseded)不在此:见 D1。
"""

from __future__ import annotations

import datetime
import re
from collections import Counter
from enum import StrEnum


class RelationType(StrEnum):
    NONE = "none"
    REVISE_REPLACE = "revise_replace"
    ABOLISH_ONLY = "abolish_only"
    MERGE = "merge"
    SPLIT_REPLACE = "split_replace"


SUPPORTED: frozenset[RelationType] = frozenset(
    {RelationType.REVISE_REPLACE, RelationType.ABOLISH_ONLY}
)

_ABOLISH = re.compile(r"^(?:abolish|废止)\s*[:：]\s*(.*)$", re.IGNORECASE)
_SEP = re.compile(r"[;,;,、]")


def parse_supersedes(cell: str | None) -> tuple[RelationType, list[str]]:
    """解析单个 supersedes 单元格 → (关系类型, 目标文件名列表)。SPLIT 不由单格判定。"""
    raw = (cell or "").strip()
    if not raw:
        return RelationType.NONE, []
    m = _ABOLISH.match(raw)
    if m:
        target = m.group(1).strip()
        return RelationType.ABOLISH_ONLY, [target] if target else []
    targets = [t.strip() for t in _SEP.split(raw) if t.strip()]
    if len(targets) >= 2:
        return RelationType.MERGE, targets
    return RelationType.REVISE_REPLACE, targets


def detect_split_targets(rows: list[tuple[str, str]]) -> set[str]:
    """批次级 split 检测:被 ≥2 个新件(单目标 revise/abolish 声明)指向的旧件名集合。

    ``rows``: ``[(filename, supersedes_cell), ...]``。merge(多目标)不计入 split 判定。
    """
    counter: Counter[str] = Counter()
    for _fn, cell in rows:
        rel, targets = parse_supersedes(cell)
        if rel in (RelationType.REVISE_REPLACE, RelationType.ABOLISH_ONLY) and len(targets) == 1:
            counter[targets[0]] += 1
    return {t for t, n in counter.items() if n >= 2}


def classify(cell: str | None, *, split_targets: set[str]) -> tuple[RelationType, list[str]]:
    """单格解析 + 批次级 split 升级:revise_replace 目标命中 split_targets → SPLIT_REPLACE。"""
    rel, targets = parse_supersedes(cell)
    if rel is RelationType.REVISE_REPLACE and targets and targets[0] in split_targets:
        return RelationType.SPLIT_REPLACE, targets
    return rel, targets


def live_status(effective_date: datetime.date | None, today: datetime.date) -> str:
    """上线时版本生命周期标量(§1.1/§7.2):生效日在 ``today`` 之后 → "upcoming",否则 "effective"。

    ``today`` 显式入参(确定性可测);生产调用方传 ``datetime.date.today()``。未来生效件 INDEXED 后置
    upcoming(默认检索不可见、不替代旧版),到生效日由 ``demo activate`` 手动翻 effective(夜间调度切)。
    """
    if effective_date is not None and effective_date > today:
        return "upcoming"
    return "effective"
