import pytest

from pipeline.chunking.normalize import (
    cn_to_int,
    normalize_clause_no,
    strip_ws,
    to_halfwidth,
)


@pytest.mark.parametrize(
    "cn,expected",
    [
        ("〇", 0),
        ("零", 0),
        ("一", 1),
        ("九", 9),
        ("十", 10),
        ("十一", 11),
        ("十九", 19),
        ("二十", 20),
        ("二十一", 21),
        ("三十", 30),
        ("九十九", 99),
        ("一百", 100),
        ("一百零五", 105),
        ("一百一十", 110),
        ("两百", 200),
        ("一千二百", 1200),
        ("21", 21),  # Arabic 透传
    ],
)
def test_cn_to_int_all_branches(cn, expected):
    assert cn_to_int(cn) == expected


def test_cn_to_int_invalid():
    with pytest.raises(ValueError):
        cn_to_int("甲")
    with pytest.raises(ValueError):
        cn_to_int("")


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("二十一", "21"),
        ("十", "10"),
        ("21", "21"),
        ("二十一之一", "21-1"),  # 中文插入条
        ("二十一之二", "21-2"),
        ("21之一", "21-1"),  # Arabic + 之
        ("21bis", "21-1"),  # 西文
        ("21ter", "21-2"),
        ("21quater", "21-3"),
        ("21BIS", "21-1"),  # 大小写不敏感
        ("21.1b", "21-1"),  # 小数式
        ("21.2", "21-2"),
        ("２１之一", "21-1"),  # 全角数字
        ("二 十 一 之 一", "21-1"),  # 逐字加空格
    ],
)
def test_normalize_clause_no(raw, expected):
    assert normalize_clause_no(raw) == expected


def test_normalize_clause_no_invalid():
    with pytest.raises(ValueError):
        normalize_clause_no("")
    with pytest.raises(ValueError):
        normalize_clause_no("第条")


def test_to_halfwidth_and_strip_ws():
    assert to_halfwidth("２１ＡＢ") == "21AB"
    assert to_halfwidth("第　一") == "第 一"  # 全角空格 → 半角
    assert strip_ws("第 一 条\t") == "第一条"
