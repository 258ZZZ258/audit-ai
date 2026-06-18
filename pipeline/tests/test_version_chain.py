"""version_chain 单测(纯逻辑,无 PG)。"""

import datetime

from pipeline.meta.version_chain import (
    SUPPORTED,
    classify,
    detect_split_targets,
    live_status,
    parse_supersedes,
)
from pipeline.meta.version_chain import (
    RelationType as RT,
)

_TODAY = datetime.date(2026, 6, 18)


def test_parse_none():
    assert parse_supersedes("") == (RT.NONE, [])
    assert parse_supersedes(None) == (RT.NONE, [])
    assert parse_supersedes("   ") == (RT.NONE, [])


def test_parse_revise_replace_single():
    assert parse_supersedes("v1.pdf") == (RT.REVISE_REPLACE, ["v1.pdf"])


def test_parse_abolish_variants():
    assert parse_supersedes("abolish:v1.pdf") == (RT.ABOLISH_ONLY, ["v1.pdf"])
    assert parse_supersedes("废止:v1.pdf") == (RT.ABOLISH_ONLY, ["v1.pdf"])  # 全角冒号
    assert parse_supersedes("ABOLISH: v1.pdf ") == (RT.ABOLISH_ONLY, ["v1.pdf"])  # 大小写+空白


def test_parse_merge_multi_target():
    assert parse_supersedes("a.pdf;b.pdf") == (RT.MERGE, ["a.pdf", "b.pdf"])
    assert parse_supersedes("a.pdf,b.pdf,c.pdf") == (RT.MERGE, ["a.pdf", "b.pdf", "c.pdf"])
    assert parse_supersedes("a.pdf;b.pdf、c.pdf") == (RT.MERGE, ["a.pdf", "b.pdf", "c.pdf"])


def test_detect_split_targets():
    rows = [("new1.pdf", "old.pdf"), ("new2.pdf", "old.pdf"), ("x.pdf", "other.pdf")]
    assert detect_split_targets(rows) == {"old.pdf"}  # old 被 2 个单目标新件指向
    assert detect_split_targets([("a.pdf", "x.pdf")]) == set()  # 单指向不算


def test_detect_split_ignores_merge():
    rows = [("n1.pdf", "old.pdf;z.pdf"), ("n2.pdf", "old.pdf")]  # n1 是 merge(多目标)
    assert detect_split_targets(rows) == set()  # old 只被 1 个单目标声明指向


def test_classify_split_upgrade():
    assert classify("old.pdf", split_targets={"old.pdf"}) == (RT.SPLIT_REPLACE, ["old.pdf"])
    assert classify("old.pdf", split_targets=set()) == (RT.REVISE_REPLACE, ["old.pdf"])


def test_supported_set():
    assert SUPPORTED == {RT.REVISE_REPLACE, RT.ABOLISH_ONLY}
    assert RT.MERGE not in SUPPORTED and RT.SPLIT_REPLACE not in SUPPORTED


def test_live_status_future_is_upcoming():
    assert live_status(_TODAY + datetime.timedelta(days=1), _TODAY) == "upcoming"
    assert live_status(datetime.date(2099, 1, 1), _TODAY) == "upcoming"


def test_live_status_past_or_today_is_effective():
    assert live_status(_TODAY - datetime.timedelta(days=1), _TODAY) == "effective"
    assert live_status(_TODAY, _TODAY) == "effective"  # 当日生效 = effective(非未来)


def test_live_status_none_is_effective():
    assert live_status(None, _TODAY) == "effective"  # 无生效日 → 立即 effective
