"""N5 充分性自检(§8.1):覆盖语境判据(非 top1 分数阈值)。

接口按 §8.1 **保真**——出参带 ``exhausted_scope``(已穷尽事项分区,供 §8.2 覆盖感知拒答);实现先
务实(事项分区高召回后命中数 ≥ 阈值即充分),升级到"事项分区穷尽"判据**不动调用方**(PLAN §2.5-3)。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Sufficiency:
    sufficient: bool
    exhausted_scope: list[str]  # 已穷尽检索的事项分区(§8.2 拒答附此)


def assess(candidates: Sequence, matters: Sequence[str], *, min_hits: int = 1) -> Sufficiency:
    """候选数 ≥ min_hits 即充分;``exhausted_scope`` = 已检索的事项分区(去重保序)。"""
    return Sufficiency(
        sufficient=len(candidates) >= max(1, min_hits),
        exhausted_scope=list(dict.fromkeys(matters)),
    )
