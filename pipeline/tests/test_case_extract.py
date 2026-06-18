"""Phase 3:L1 案例要素抽取纯单测(无栈,无 LLM)。文号/日期/金额/类型/当事人类型。"""

from __future__ import annotations

from pipeline.meta.case_extract import extract_case

_SAMPLE_ORG = """北京证监局
京证监〔2024〕5号
行政处罚决定书
当事人:某某证券有限公司,住所地北京市朝阳区。
经查,该公司存在以下违规行为:未按规定披露重大信息。
依据《证券法》第一百九十七条的规定,
现决定:对当事人给予警告,并处以罚款50万元。
2024年3月15日
"""

_SAMPLE_PERSON = """上海证监局
当事人:张三,男,身份证号110101199001011234,住址上海市浦东新区。
经查,张三存在内幕交易行为。
现决定:对张三处以没收违法所得及罚款共计120000元,并采取市场禁入措施。
2023年12月1日
"""


def test_extracts_doc_number_date_amount() -> None:
    c = extract_case(_SAMPLE_ORG, {"issuer": "北京证监局"})
    assert c["doc_number"] == "京证监[2024]5号"  # to_halfwidth 归一括号
    assert c["penalty_date"] == "2024-03-15"  # ISO 字符串(s4 转 date)
    assert c["amount_wan"] == 50.0  # 「50万元」→ 50.0 Float


def test_extracts_org_respondent_and_type_org() -> None:
    c = extract_case(_SAMPLE_ORG, {"issuer": "x"})
    assert c["penalty_org"] == "北京证监局"  # 头部机构抬头优先于 manifest
    assert c["respondent"] == "某某证券有限公司"
    assert c["respondent_type"] == "机构"  # 无个人特征 → 机构
    assert "警告" in c["penalty_type"] and "罚款" in c["penalty_type"]


def test_person_respondent_type_and_yuan_to_wan() -> None:
    c = extract_case(_SAMPLE_PERSON, {})
    assert c["respondent"] == "张三"
    assert c["respondent_type"] == "个人"  # 身份证/性别/住址 → 个人
    assert c["amount_wan"] == 12.0  # 「120000元」→ 12.0 万元
    assert "没收" in c["penalty_type"] and "市场禁入" in c["penalty_type"]


def test_l2_fields_left_unset() -> None:
    c = extract_case(_SAMPLE_ORG, {"issuer": "x"})
    assert c["violation_category"] is None  # L2 LLM 字段,本阶段不抽
    assert c["cited_regulations"] == []
    assert c["ref_unresolved"] is False


def test_org_falls_back_to_manifest_issuer() -> None:
    # 头部无机构抬头 → 用 manifest issuer 兜底
    c = extract_case("当事人:某公司。经查存在违规。", {"issuer": "深圳证监局"})
    assert c["penalty_org"] == "深圳证监局"


def test_no_amount_returns_none() -> None:
    c = extract_case("当事人:某公司。现决定:责令改正。", {})
    assert c["amount_wan"] is None
    assert c["penalty_type"] == "责令"
