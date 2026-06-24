"""R4-T1(单元):列举维度抽取——义务意图 / 词典抽取 / chunk_type 偏好。零栈零模型。"""

from __future__ import annotations

from query.listing.dimensions import EnumSpec, extract_enum_spec

_BIZ = ("反洗钱", "客户身份识别", "适当性管理")
_ENTITY = ("C类营业部", "证券公司")


def test_returns_enum_spec():
    s = extract_enum_spec("哪些制度规定了客户身份识别")
    assert isinstance(s, EnumSpec)


def test_obligation_intent_triggers():
    # "要求 / 义务 / 必须 / 应当 / 禁止 / 不得" → obligation_only(Q3)
    for q in (
        "列出所有关于反洗钱的要求",
        "反洗钱有哪些义务",
        "客户身份识别必须做什么",
        "哪些行为不得从事",
    ):
        assert extract_enum_spec(q).obligation_only is True, q


def test_non_obligation_listing_not_triggered():
    # "制度 / 规定 / 哪些" 列举型不触发义务过滤(避免"列出制度"被误缩为义务)
    for q in ("哪些制度规定了客户身份识别", "列出所有关于反洗钱的制度", "有哪些规定"):
        assert extract_enum_spec(q).obligation_only is False, q


def test_biz_and_entity_extracted_from_dict():
    s = extract_enum_spec(
        "C类营业部的反洗钱有哪些规定", biz_terms=_BIZ, entity_terms=_ENTITY
    )
    assert s.biz_domains == ["反洗钱"]
    assert s.entity_types == ["C类营业部"]


def test_chunk_type_pref_default_true():
    assert extract_enum_spec("哪些制度规定了反洗钱").chunk_type_pref is True


def test_empty_dict_yields_empty_filters():
    # 词典未注入 → biz/entity 空(consumed-when-present:不过滤降级)
    s = extract_enum_spec("哪些制度规定了反洗钱")
    assert s.biz_domains == [] and s.entity_types == []


def test_malicious_text_not_in_spec():
    # 防注入:非词典成员(恶意串)绝不进 spec —— extract_terms 只返词典成员
    mal = 'C类营业部"; drop table chunks;-- or 1=1'
    s = extract_enum_spec(mal, biz_terms=_BIZ, entity_terms=_ENTITY)
    # 命中的只有词典词 C类营业部;恶意尾串不进任何字段
    assert s.entity_types == ["C类营业部"]
    assert all("drop" not in v and "1=1" not in v for v in s.biz_domains + s.entity_types)
