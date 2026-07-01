"""T2(SPEC-API §4):结构化四-Tab 装配纯函数。

无栈单测:``assemble_structured`` 只吃「候选 + 预取 PG 数据」(SimpleNamespace 鸭子类型),
不碰真栈。PG 回查(``fetch_pg_context``)留集成测。断言:分区(内规/外规/案例)、匹配度 min-max
归一、⚠-data/⚠-model 缺省省略(零臆造)、案例要素逐字、按文档去重 vs 逐条款。
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from query.api.structured import assemble_structured
from query.retrieve.hybrid import Candidate


def _cand(cid, score, corpus, dvid) -> Candidate:
    return Candidate(
        chunk_id=cid, score=score, corpus_type=corpus, doc_version_id=dvid,
        clause_path=None, page_start=None, degraded=False, retrieval_mode="hybrid",
    )


def _chunk(dvid, clause_path, text):
    return SimpleNamespace(doc_version_id=dvid, clause_path=clause_path, text=text)


def _dv(title, doc_number=None, issue=None, eff=None, issuer=None, status="effective"):
    return SimpleNamespace(
        title=title, doc_number=doc_number, issue_date=issue,
        effective_date=eff, issuer=issuer, version_status=status,
    )


def _case(org=None, pdate=None, vcat=None, cited=None):
    return SimpleNamespace(
        penalty_org=org, penalty_date=pdate, violation_category=vcat, cited_regulations=cited,
    )


def test_partition_internal_external_case_counts():
    cands = [
        _cand("i1", 9.0, "P-INT", "DV1"),
        _cand("i2", 7.0, "P-INT", "DV1"),   # 同 DV1 → 制度去重为 1,条款为 2
        _cand("i3", 6.0, "P-INT", "DV2"),
        _cand("e1", 8.0, "P-EXT", "DE1"),
    ]
    case_cands = [_cand("c1", 5.0, "P-CASE", "DC1")]
    chunk_doc = {
        "i1": (_chunk("DV1", "第三章/第三条 适还比例", "条文i1"), _dv("《适当性细则》")),
        "i2": (_chunk("DV1", "第三章/第五条 银保监法", "条文i2"), _dv("《适当性细则》")),
        "i3": (_chunk("DV2", "第一章/第一条", "条文i3"), _dv("《往来指引》")),
        "e1": (_chunk("DE1", "第十八条 境外服务", "外规e1"), _dv("《境外服务规定》")),
    }
    case_rows = {"DC1": (_case(org="上海证监局", pdate=date(2024, 10, 17)), _dv("某案"))}

    s = assemble_structured(cands, case_cands, chunk_doc, case_rows)
    d = s.to_dict()
    assert d["regulations"]["total"] == 2   # 命中制度:DV1/DV2 去重
    assert d["clauses"]["total"] == 3       # 命中条款:i1/i2/i3 逐条
    assert d["regulatory_rules"]["total"] == 1  # 监管规则:DE1
    assert d["cases"]["total"] == 1         # 相关案例:DC1
    # ⚠-model 卡片/引用建议默认空(LLM 关)
    assert d["citation_advice"] == [] and d["regulatory_digest"] == [] and d["case_insights"] == []


def test_match_score_minmax_normalized_over_retrieve_set():
    cands = [_cand("i1", 9.0, "P-INT", "DV1"), _cand("i3", 6.0, "P-INT", "DV2"),
             _cand("e1", 8.0, "P-EXT", "DE1")]
    chunk_doc = {
        "i1": (_chunk("DV1", "第三条", "x"), _dv("A")),
        "i3": (_chunk("DV2", "第一条", "x"), _dv("B")),
        "e1": (_chunk("DE1", "第十八条", "x"), _dv("C")),
    }
    d = assemble_structured(cands, [], chunk_doc, {}).to_dict()
    clauses = {c["clause_id"]: c["match_score"] for c in d["clauses"]["items"]}
    assert clauses["i1"] == 1.0   # 全集 max=9 → 1.0
    assert clauses["i3"] == 0.0   # 全集 min=6 → 0.0
    regs = {r["doc_id"]: r["match_score"] for r in d["regulations"]["items"]}
    assert regs["DV1"] == 1.0 and regs["DV2"] == 0.0   # 命中制度同一归一窗口
    assert "match_score" not in d["regulatory_rules"]["items"][0]  # 监管规则无匹配度列


def test_regulation_fields_and_dedup_keep_best_score():
    cands = [_cand("i1", 9.0, "P-INT", "DV1"), _cand("i2", 7.0, "P-INT", "DV1")]
    chunk_doc = {
        "i1": (_chunk("DV1", "第三条", "高分节选"), _dv(
            "《客户适当性管理实施细则》", doc_number="NEEQ-QF-2020-034",
            issue=date(2021, 2, 1), eff=date(2022, 2, 15), issuer="合规管理部")),
        "i2": (_chunk("DV1", "第五条", "低分节选"), _dv("《客户适当性管理实施细则》")),
    }
    s = assemble_structured(cands, [], chunk_doc, {})
    regs = s.to_dict()["regulations"]["items"]
    assert len(regs) == 1
    r = regs[0]
    assert r["title"].startswith("《客户适当性")
    assert r["doc_no"] == "NEEQ-QF-2020-034"
    assert r["publish_date"] == "2021-02-01" and r["effective_date"] == "2022-02-15"
    assert r["issuing_dept"] == "合规管理部" and r["status"] == "effective"
    assert r["match_score"] == 1.0 and r["clause_excerpt"] == "高分节选"  # 取最高分块节选


def test_clause_theme_omitted_summary_present():
    cands = [_cand("i1", 9.0, "P-INT", "DV1")]
    chunk_doc = {"i1": (_chunk("DV1", "第三章 识别/第三条 适还比例界定", "条款正文摘要"), _dv("A"))}
    c = assemble_structured(cands, [], chunk_doc, {}).to_dict()["clauses"]["items"][0]
    assert c["clause_title"] == "第三条 适还比例界定"   # clause_path 末段
    assert c["summary"] == "条款正文摘要"               # ⚠-model:默认截断兜底
    assert "theme" not in c                             # ⚠-data:无打标 → 省略


def test_case_verbatim_and_l2_omitted_when_absent():
    case_cands = [_cand("c1", 5.0, "P-CASE", "DC1"), _cand("c2", 4.0, "P-CASE", "DC2")]
    case_rows = {
        "DC1": (_case(org="上海证监局", pdate=date(2024, 10, 17),
                      vcat="适当性评估不足", cited=["《资管产品适当性管理办法》"]),
                _dv("某商业银行理财子公司未有效评估客户风险等级案")),
        "DC2": (_case(org="深圳证监局", pdate=date(2024, 6, 21)), _dv("某案二")),  # L2 缺
    }
    cases = assemble_structured([], case_cands, {}, case_rows).to_dict()["cases"]["items"]
    c1, c2 = cases[0], cases[1]
    assert c1["regulator"] == "上海证监局" and c1["penalty_date"] == "2024-10-17"
    assert c1["violation_theme"] == "适当性评估不足"
    assert c1["related_regulations"] == ["《资管产品适当性管理办法》"]
    assert "core_issue" not in c1 and "insight" not in c1  # LLM 关 → 省略
    # DC2 的 L2 字段缺失 → 省略(零臆造)
    assert "violation_theme" not in c2 and "related_regulations" not in c2


def test_empty_inputs_all_tabs_zero():
    s = assemble_structured([], [], {}, {}).to_dict()
    for tab in ("regulations", "clauses", "regulatory_rules", "cases"):
        assert s[tab] == {"total": 0, "items": []}
