"""L1 规则抽取 + 交叉校验单测(纯逻辑,无 PG)。"""

from datetime import date

from pipeline.ir import Block, BlockType, IRDocument, SourceFormat
from pipeline.meta.l1_rules import L1Meta, cross_check, extract, resolve_issuer

ISSUERS = [("CSRC", "中国证券监督管理委员会"), ("SSE", "上海证券交易所")]


def _ir(title, paras):
    p = BlockType.PARAGRAPH
    return IRDocument(
        doc_version_id="DV", source_format=SourceFormat.DOCX, title=title,
        blocks=[Block(index=i, type=p, text=t, page=1) for i, t in enumerate(paras)],
    )


def _cc(meta, **kw):
    base = {"doc_number": None, "issue_date": None, "issuer_code": None, "title": None}
    return cross_check(meta, **{**base, **kw})


def test_extract_all_fields():
    ir = _ir(
        "某单位综合管理办法",
        ["中国证券监督管理委员会", "京证监〔2024〕5号", "第一条 略。", "2024年1月1日"],
    )
    m = extract(ir, ISSUERS)
    assert "京证监〔2024〕5号" in m.doc_numbers
    assert date(2024, 1, 1) in m.dates
    assert m.issuer_codes == ("CSRC",)
    assert m.title == "某单位综合管理办法"


def test_extract_misses_gracefully():
    m = extract(_ir("无版头", ["第一条 正文。", "第二条 正文。"]), ISSUERS)
    assert m.doc_numbers == () and m.dates == () and m.issuer_codes == ()


def test_resolve_issuer():
    assert resolve_issuer("CSRC", ISSUERS) == "CSRC"  # 填 code
    assert resolve_issuer("中国证券监督管理委员会", ISSUERS) == "CSRC"  # 填 name
    assert resolve_issuer("未知机构", ISSUERS) is None
    assert resolve_issuer(None, ISSUERS) is None


def test_cross_check_consistent_no_conflict():
    m = L1Meta(("京证监〔2024〕5号",), (date(2024, 1, 1),), ("CSRC",), "某办法")
    assert _cc(m, doc_number="京证监〔2024〕5号", issue_date=date(2024, 1, 1),
               issuer_code="CSRC", title="某办法") == []


def test_doc_number_conflict():
    m = L1Meta(("京证监〔2024〕5号",), (), (), None)
    c = _cc(m, doc_number="京证监〔2024〕9号")
    assert len(c) == 1 and c[0].field == "doc_number"


def test_doc_number_bracket_variant_not_conflict():
    m = L1Meta(("京证监〔2024〕5号",), (), (), None)  # 〔〕 vs [] 归一后相等
    assert _cc(m, doc_number="京证监[2024]5号") == []


def test_date_membership():
    m = L1Meta((), (date(2024, 1, 1), date(2025, 1, 1)), (), None)
    assert _cc(m, issue_date=date(2024, 1, 1)) == []  # 在候选中
    c = _cc(m, issue_date=date(2023, 1, 1))  # 不在候选中
    assert len(c) == 1 and c[0].field == "issue_date"


def test_issuer_conflict():
    m = L1Meta((), (), ("CSRC",), None)
    assert _cc(m, issuer_code="CSRC") == []
    c = _cc(m, issuer_code="SSE")
    assert len(c) == 1 and c[0].field == "issuer"


def test_title_conflict_after_normalize():
    m = L1Meta((), (), (), "某单位管理办法")
    assert _cc(m, title="某 单位 管理办法") == []  # 归一去空白后相等
    c = _cc(m, title="完全不同的标题")
    assert len(c) == 1 and c[0].field == "title"


def test_skips_when_manifest_empty_or_l1_missing():
    empty = L1Meta((), (), (), None)  # L1 全空 → 任何 manifest 都不冲突
    assert _cc(empty, doc_number="X号", issue_date=date(2024, 1, 1),
               issuer_code="CSRC", title="T") == []
    got = L1Meta(("京证监〔2024〕5号",), (), (), None)  # manifest 空 → 不冲突
    assert _cc(got, doc_number=None) == []
