"""R4-T2/T4(单元):build_milvus_expr 防注入 + answer_enumerate 编排。零栈零模型。

T2 安全节(本文件上半):expr 字段名白名单 + 值仅词典 + 恶意串不破结构。
T4 编排节(下半,T4 落地后追加):按 doc 聚合 / E1 后过滤 / 空→拒答 / 边界声明。
"""

from __future__ import annotations

from query.listing.dimensions import EnumSpec
from query.listing.r4_listing import _ALLOWED_EXPR_FIELDS, build_milvus_expr

# ── T2:build_milvus_expr 防注入(安全核心)────────────────────────────────────


def test_chunk_type_pref_only():
    # 仅 chunk_type 偏好(biz/entity 空)→ 硬过滤 clause
    expr = build_milvus_expr(EnumSpec(chunk_type_pref=True))
    assert expr == 'chunk_type == "clause"'


def test_empty_spec_returns_none():
    # 无任何过滤维度 → None(不附加 expr)
    assert build_milvus_expr(EnumSpec(chunk_type_pref=False)) is None


def test_biz_and_entity_array_contains_any():
    expr = build_milvus_expr(
        EnumSpec(chunk_type_pref=True, biz_domains=["反洗钱"], entity_types=["C类营业部"])
    )
    assert 'chunk_type == "clause"' in expr
    assert 'array_contains_any(biz_domain, ["反洗钱"])' in expr
    assert 'array_contains_any(entity_type, ["C类营业部"])' in expr
    assert " and " in expr  # AND 连接


def test_field_names_whitelist_only():
    # expr 只可能出现白名单字段名,绝不出现其它列名
    expr = build_milvus_expr(
        EnumSpec(chunk_type_pref=True, biz_domains=["反洗钱"], entity_types=["证券公司"])
    )
    assert _ALLOWED_EXPR_FIELDS == frozenset({"chunk_type", "biz_domain", "entity_type"})
    for forbidden in ("status", "perm_tag", "text", "doc_version_id", "drop", "delete"):
        assert forbidden not in expr


def test_malicious_value_cannot_break_structure():
    # 防注入纵深:即便 EnumSpec 携恶意值(绕过 dimensions 词典),引号经 JSON 转义、不破 expr 结构
    expr = build_milvus_expr(EnumSpec(chunk_type_pref=False, biz_domains=['x" or 1==1']))
    # 内嵌 " 被转义为 \" → 整体仍是单个 array_contains_any 的字符串实参,无法注入新谓词
    assert expr == r'array_contains_any(biz_domain, ["x\" or 1==1"])'


# ── T4:answer_enumerate 编排(按 doc 聚合 / E1 后过滤 / 空→拒答 / 边界声明)────────

import json  # noqa: E402

from query.contract import BlockType, Citation, RouteType  # noqa: E402
from query.listing import r4_listing  # noqa: E402
from query.listing.r4_listing import answer_enumerate  # noqa: E402
from query.retrieve.hybrid import Candidate  # noqa: E402


def _cand(cid, dvid, clause, score=1.0, *, degraded=False):
    return Candidate(
        chunk_id=cid, score=score, corpus_type="P-INT", doc_version_id=dvid,
        clause_path=clause, page_start=1, degraded=degraded, retrieval_mode="hybrid",
    )


class _FakeRetriever:
    def __init__(self, cands):
        self._cands = cands
        self.last_extra_expr = "UNSET"

    def retrieve_enumerate(self, query, *, extra_expr=None, include_superseded=False):
        self.last_extra_expr = extra_expr
        return list(self._cands)


def _patch_anchors(monkeypatch, cands):
    """fetch_anchors stub:每 chunk → 四级 Citation(doc_title=dvid 派生,status=effective)。"""
    def _fake(pg, ids):
        out = {}
        by_id = {c.chunk_id: c for c in cands}
        for cid in ids:
            c = by_id.get(cid)
            if c is None:
                continue
            out[cid] = Citation(
                clause_id=cid, doc_title=f"《{c.doc_version_id}制度》",
                doc_no=f"号-{c.doc_version_id}", clause_path=c.clause_path,
                page_start=c.page_start, status="effective",
            )
        return out
    monkeypatch.setattr(r4_listing, "fetch_anchors", _fake)


def test_aggregates_by_document(monkeypatch):
    cands = [_cand("a1", "DOC1", "1/1", 0.9), _cand("a2", "DOC1", "1/2", 0.8),
             _cand("b1", "DOC2", "2/1", 0.7)]
    _patch_anchors(monkeypatch, cands)
    res = answer_enumerate("哪些制度规定了反洗钱", _FakeRetriever(cands), pg=None)
    assert res.route_type is RouteType.ENUMERATE
    block = res.answer_blocks[0]
    assert block.type is BlockType.TABLE and block.stream is False
    content = json.loads(block.content)
    assert len(content["rows"]) == 2          # 两文档各一行(DOC1 合两条款)
    assert "不保证穷举外规" in content["note"]   # 边界声明
    assert len(res.citations) == 3            # 每命中条款一条四级锚点


def test_obligation_filter_keeps_only_obligation(monkeypatch):
    cands = [_cand("a1", "DOC1", "1/1"), _cand("b1", "DOC2", "2/1")]
    _patch_anchors(monkeypatch, cands)
    monkeypatch.setattr(r4_listing, "fetch_obligation_chunk_ids", lambda pg, ids: {"a1"})
    res = answer_enumerate("列出所有关于反洗钱的要求", _FakeRetriever(cands), pg=None)
    content = json.loads(res.answer_blocks[0].content)
    assert len(content["rows"]) == 1          # 仅义务条款 a1 所在 DOC1
    assert [c.clause_id for c in res.citations] == ["a1"]


def test_obligation_degrade_when_no_tags(monkeypatch):
    cands = [_cand("a1", "DOC1", "1/1"), _cand("b1", "DOC2", "2/1")]
    _patch_anchors(monkeypatch, cands)
    monkeypatch.setattr(r4_listing, "fetch_obligation_chunk_ids", lambda pg, ids: set())
    res = answer_enumerate("列出所有关于反洗钱的要求", _FakeRetriever(cands), pg=None)
    content = json.loads(res.answer_blocks[0].content)
    assert len(content["rows"]) == 2          # E1 空→降级不过滤(consumed-when-present)
    assert "义务标签" in content["note"]        # 降级明示


def test_empty_candidates_refuses(monkeypatch):
    _patch_anchors(monkeypatch, [])
    res = answer_enumerate("哪些制度规定了反洗钱", _FakeRetriever([]), pg=None)
    assert res.route_type is RouteType.REFUSE
    assert res.exhausted_scope  # 非空(可解释)


def test_extra_expr_threaded_with_chunk_type(monkeypatch):
    cands = [_cand("a1", "DOC1", "1/1")]
    _patch_anchors(monkeypatch, cands)
    r = _FakeRetriever(cands)
    answer_enumerate("哪些制度规定了反洗钱", r, pg=None)
    assert r.last_extra_expr == 'chunk_type == "clause"'  # 默认硬偏好 clause


def test_biz_filter_in_extra_expr(monkeypatch):
    cands = [_cand("a1", "DOC1", "1/1")]
    _patch_anchors(monkeypatch, cands)
    r = _FakeRetriever(cands)
    answer_enumerate("哪些制度规定了反洗钱", r, pg=None, biz_terms=["反洗钱"])
    assert 'array_contains_any(biz_domain, ["反洗钱"])' in r.last_extra_expr
