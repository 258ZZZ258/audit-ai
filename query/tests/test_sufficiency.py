"""T9:充分性自检——命中阈值判据 + exhausted_scope(接口按 §8.1 保真)。"""

from __future__ import annotations

from query.retrieve.sufficiency import assess


def test_sufficient_when_hits_meet_threshold():
    r = assess([1, 2, 3], ["投顾业务"], min_hits=1)
    assert r.sufficient is True
    assert r.exhausted_scope == ["投顾业务"]


def test_insufficient_when_no_hits():
    r = assess([], ["投顾业务", "投顾业务"], min_hits=1)
    assert r.sufficient is False
    assert r.exhausted_scope == ["投顾业务"]  # 去重保序;供拒答可解释


def test_min_hits_threshold():
    assert assess([1], [], min_hits=2).sufficient is False
    assert assess([1, 2], [], min_hits=2).sufficient is True
