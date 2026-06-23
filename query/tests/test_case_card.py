"""T1(单元):案例卡片组卡——present/absent 字段、JSON 形状、L2 空字段省略、零臆造。

零栈零模型:输入用 ``SimpleNamespace`` 仿 PG 行(``cases`` / ``doc_versions``)。
"""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

from query.case.case_card import CaseCard, build_case_card
from query.contract import BlockType


def _case(**kw):
    base = dict(
        doc_version_id="DV1",
        penalty_org="XX证监局",
        doc_number="〔2024〕1号",
        penalty_date=date(2024, 3, 11),
        respondent="XX公司",
        respondent_type="机构",
        violation_category=None,      # L2 默认空
        cited_regulations=[],         # L2 默认空
        penalty_type="警告/罚款",
        amount_wan=50.0,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _dv(**kw):
    base = dict(
        title="XX证监局行政处罚决定书",
        doc_number="〔2024〕1号",
        issue_date=date(2024, 3, 11),
        version_status="effective",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_build_case_card_block_type_and_json():
    blk = build_case_card(_case(), _dv())
    assert blk.type is BlockType.CASE_CARD
    d = json.loads(blk.content)
    assert d["doc_version_id"] == "DV1"
    assert d["title"] == "XX证监局行政处罚决定书"   # 标题取 doc_meta 权威
    assert d["penalty_org"] == "XX证监局"
    assert d["penalty_date"] == "2024-03-11"        # date → ISO
    assert d["respondent"] == "XX公司"
    assert d["penalty_type"] == "警告/罚款"
    assert d["amount_wan"] == 50.0


def test_l2_empty_fields_omitted():
    blk = build_case_card(_case(violation_category=None, cited_regulations=[]), _dv())
    d = json.loads(blk.content)
    assert "violation_category" not in d   # L2 None → 省略
    assert "cited_regulations" not in d     # L2 [] → 省略


def test_l2_present_fields_shown():
    d = json.loads(
        build_case_card(
            _case(violation_category="违规开户", cited_regulations=["《证券法》第58条"]), _dv()
        ).content
    )
    assert d["violation_category"] == "违规开户"
    assert d["cited_regulations"] == ["《证券法》第58条"]


def test_missing_l1_fields_omitted_no_fabrication():
    # 缺失 L1 字段(None)→ 不臆造、不进 JSON;身份字段恒在
    d = json.loads(
        build_case_card(
            _case(penalty_org=None, respondent=None, amount_wan=None), _dv(title=None)
        ).content
    )
    assert "penalty_org" not in d and "respondent" not in d and "amount_wan" not in d
    assert "title" not in d
    assert d["doc_version_id"] == "DV1"


def test_card_doc_meta_none_no_error():
    # doc_meta None(doc_versions 未命中)→ title 省略,不报错
    d = json.loads(build_case_card(_case(), None).content)
    assert "title" not in d
    assert d["doc_version_id"] == "DV1"


def test_card_stream_false_atomic():
    # 结构化卡片为原子块,不逐 token 流式
    assert build_case_card(_case(), _dv()).stream is False


def test_from_rows_returns_casecard():
    card = CaseCard.from_rows(_case(), _dv())
    assert isinstance(card, CaseCard)
    assert card.doc_version_id == "DV1" and card.penalty_date == "2024-03-11"
