"""案例 L2(§9):T2.1 引用外规抽取+归一对齐 / T2.2 违规事由分类(dict 约束)。

纯助手单元(免栈、免真 LLM,注入 ``FakeClient`` / ``FakeLookup``)+ 装配非阻断 +
真模型门控集成。**绝不发真 OpenAI 请求**:单元用例全注入 fake;门控集成测仅在
``OPENAI_API_KEY`` 存在且 PG 可达时跑(绝不联网)。
"""

from __future__ import annotations

import os
import types
from contextlib import contextmanager

import pytest

from pipeline.meta import case_l2
from pipeline.meta.case_ref_align import RegDoc


class FakeClient:
    """注入式假 LLM:记调用数;``response`` 为 dict 直接返回,或 callable(system, user) 分流。"""

    def __init__(self, response=None):
        self._response = response if response is not None else {}
        self.calls = 0

    def chat_json(self, system: str, user: str):
        self.calls += 1
        if callable(self._response):
            return self._response(system, user)
        return self._response


class FakeLookup:
    """注入式外规查询(case_ref_align.RegLookup):按文号 / 标题命中预置 RegDoc。"""

    def __init__(self, by_doc=None, by_title=None):
        self._by_doc = by_doc or {}
        self._by_title = by_title or {}

    def find(self, doc_number, title):
        if doc_number and doc_number in self._by_doc:
            return self._by_doc[doc_number]
        if title and title in self._by_title:
            return self._by_title[title]
        return None


def _route(cited=None, violation=None):
    """造一个按 system 内容分流 cited / violation 的 fake chat。"""

    def chat(system, user):
        if "引用外规" in system:
            return {"cited": cited or []}
        if "违规事由" in system:
            return {"violation_category": violation}
        return {}

    return chat


# ── T2.1 单元:抽引用外规 prompt + 形态/裁剪/降级 ───────────────────────────
def test_build_cited_prompt_has_rules_and_text():
    system, user = case_l2.build_cited_prompt("当事人 X,依据《证券法》第十五条,现决定...")
    assert "不臆测" in system and "JSON" in system and "cited" in system
    assert "证券法" in user and "第十五条" in user  # 待抽全文进 user


def test_extract_cited_normalizes_items():
    cited = [
        {"title": "证券公司监督管理条例", "doc_number": "〔2020〕5号", "clause": "第十五条第二款"},
        {"title": "证券法", "doc_number": None, "clause": None},
    ]
    assert case_l2.extract_cited(FakeClient({"cited": cited}), "t") == cited


def test_extract_cited_drops_items_without_anchor():
    client = FakeClient({
        "cited": [
            {"clause": "第三条"},  # 无 title/doc_number → 丢(无对齐锚点)
            {"title": "", "doc_number": ""},  # 空串 → 丢
            {"title": "有效法规"},  # 仅 title → 留(doc_number/clause 补 None)
            "not-a-dict",  # 非 dict → 丢
        ]
    })
    assert case_l2.extract_cited(client, "t") == [
        {"title": "有效法规", "doc_number": None, "clause": None}
    ]


def test_extract_cited_handles_bad_response():
    assert case_l2.extract_cited(FakeClient("not json"), "t") == []
    assert case_l2.extract_cited(FakeClient({}), "t") == []
    assert case_l2.extract_cited(FakeClient({"cited": "not-list"}), "t") == []


# ── T2.2 单元:违规事由 prompt + dict 裁剪 + 空降级 ──────────────────────────
def test_build_violation_prompt_includes_allowed_and_rules():
    system, user = case_l2.build_violation_prompt("案情...", ["信息披露违规", "内幕交易"])
    assert "严格来自" in system and "不臆测" in system
    assert "信息披露违规" in user and "内幕交易" in user
    assert "violation_category" in system


def test_classify_violation_in_dict_returns_value_and_version():
    allowed = {"信息披露违规": "v0-draft-2026-06", "内幕交易": "v0-draft-2026-06"}
    client = FakeClient({"violation_category": "信息披露违规"})
    cat, ver = case_l2.classify_violation(client, "x", allowed)
    assert cat == "信息披露违规"
    assert ver == "v0-draft-2026-06"


def test_classify_violation_out_of_dict_drops_to_none():
    allowed = {"信息披露违规": "v0"}
    client = FakeClient({"violation_category": "火星违规"})
    cat, ver = case_l2.classify_violation(client, "x", allowed)
    assert cat is None and ver is None


def test_classify_violation_empty_dict_skips_llm():
    client = FakeClient({"violation_category": "x"})
    cat, ver = case_l2.classify_violation(client, "x", {})
    assert cat is None and ver is None
    assert client.calls == 0  # 字典空 → 不调 LLM(consumed-when-present)


def test_classify_violation_handles_bad_response():
    allowed = {"信息披露违规": "v0"}
    cat, ver = case_l2.classify_violation(FakeClient("nope"), "x", allowed)
    assert cat is None and ver is None


# ── 装配 l2_fields:抽取 → 对齐 → 分类,产出 case 字段 ───────────────────────
def test_l2_fields_wires_cited_align_and_violation():
    regdoc = RegDoc(
        doc_version_id="dv1", doc_number="〔2020〕5号", clause_norms=frozenset({"2/15"})
    )
    lookup = FakeLookup(by_doc={"〔2020〕5号": regdoc})
    allowed = {"信息披露违规": "v0-draft-2026-06"}
    client = FakeClient(
        _route(
            cited=[{"title": "条例", "doc_number": "〔2020〕5号", "clause": "第十五条"}],
            violation="信息披露违规",
        )
    )
    out = case_l2.l2_fields("案情", client=client, lookup=lookup, allowed_violations=allowed)
    assert out["cited_regulations"] == [
        {"doc_number": "〔2020〕5号", "title": "条例", "clause_path_norm": "2/15", "resolved": True}
    ]
    assert out["ref_unresolved"] is False
    assert out["violation_category"] == "信息披露违规"
    assert out["violation_category_dict_version"] == "v0-draft-2026-06"


def test_l2_fields_unresolved_when_lookup_miss():
    cited = [{"title": "未知法规", "doc_number": None, "clause": "第三条"}]
    client = FakeClient(_route(cited=cited, violation=None))
    out = case_l2.l2_fields("案情", client=client, lookup=FakeLookup(), allowed_violations={})
    assert out["ref_unresolved"] is True
    assert out["cited_regulations"][0]["resolved"] is False
    assert out["violation_category"] is None
    assert out["violation_category_dict_version"] is None


def test_l2_fields_no_citation_keeps_empty():
    client = FakeClient(_route(cited=[], violation=None))
    out = case_l2.l2_fields("案情", client=client, lookup=FakeLookup(), allowed_violations={})
    assert out["cited_regulations"] == []
    assert out["ref_unresolved"] is False


# ── 装配 apply:合并进 case fields + 非阻断(LLM/对齐失败不阻塞案例入库,§9)──────
class _FakeDb:
    def __init__(self, violation_types=None):
        self._vts = violation_types or []

    def get_violation_types(self):
        return self._vts


def test_apply_merges_l2_into_fields(monkeypatch):
    monkeypatch.setattr(
        case_l2,
        "l2_fields",
        lambda *a, **k: {
            "cited_regulations": [
                {"doc_number": "X", "title": None, "clause_path_norm": "3", "resolved": True}
            ],
            "ref_unresolved": False,
            "violation_category": "信息披露违规",
            "violation_category_dict_version": "v0",
        },
    )
    ctx = types.SimpleNamespace(db=_FakeDb())
    fields = {"violation_category": None, "cited_regulations": [], "ref_unresolved": False}
    case_l2.apply(ctx, "案情", fields, client=object())
    assert fields["violation_category"] == "信息披露违规"
    assert fields["violation_category_dict_version"] == "v0"
    assert fields["cited_regulations"][0]["resolved"] is True


def test_apply_nonblocking_on_llm_error():
    class BoomClient:
        def chat_json(self, system, user):
            raise RuntimeError("LLM 炸了")

    ctx = types.SimpleNamespace(db=_FakeDb())
    fields = {"violation_category": None, "cited_regulations": [], "ref_unresolved": False}
    case_l2.apply(ctx, "案情", fields, client=BoomClient())  # 不抛
    assert fields == {
        "violation_category": None,
        "cited_regulations": [],
        "ref_unresolved": False,
    }


# ── 栈集成:真 PgRegLookup + 真 dict 加载(栈起即跑,无需 key)+ 真模型门控 ──────────
@pytest.fixture
def pg_ctx():
    from sqlalchemy import text

    from pipeline.config import load_config
    from pipeline.index.object_store import ObjectStore
    from pipeline.index.pg_io import PgIO
    from pipeline.stage_base import StageContext

    cfg = load_config()
    pg = PgIO.from_config(cfg)
    try:
        with pg.session() as s:
            s.execute(text("select 1"))
    except Exception:
        pytest.skip("PG 不可达")
    return cfg, pg, StageContext(config=cfg, object_store=ObjectStore.from_config(cfg), db=pg)


@contextmanager
def _seeded_ext_reg(pg, doc_no: str, title: str, clause_norm: str):
    """播一篇被引外规(P-EXT,effective)+ 一条 ``clause_path_norm`` 条款块,供对齐命中。"""
    from sqlalchemy import delete
    from ulid import ULID

    from common.pg_models import Chunk, Document, DocVersion, ImportBatch

    bid, lid, dvid = "cl2_" + str(ULID()), str(ULID()), str(ULID())
    with pg.session() as s:
        s.add(ImportBatch(batch_id=bid, source_dir="x"))
        s.add(Document(logical_id=lid, corpus_type="P-EXT"))
        s.flush()
        s.add(
            DocVersion(
                doc_version_id=dvid, logical_id=lid, batch_id=bid, source_format="docx",
                source_hash="h" + dvid[:8], raw_object_key="k", pipeline_status="INDEXED",
                version_status="effective", doc_number=doc_no, title=title,
            )
        )
        s.flush()
        s.add(
            Chunk(
                chunk_id=("cl2c" + dvid)[:24], doc_version_id=dvid, text="第十五条 应当披露",
                clause_path=clause_norm, clause_path_norm=clause_norm, seq=0, page_start=1,
                is_parent=False, is_table=False, chunk_status="effective",
            )
        )
    try:
        yield dvid
    finally:
        with pg.session() as s:
            s.execute(delete(Chunk).where(Chunk.doc_version_id == dvid))
            s.execute(delete(DocVersion).where(DocVersion.doc_version_id == dvid))
            s.execute(delete(Document).where(Document.logical_id == lid))
            s.execute(delete(ImportBatch).where(ImportBatch.batch_id == bid))


def test_apply_real_pg_fake_llm_resolves_and_classifies(pg_ctx):
    """真 PgRegLookup(按文号命中外规 + 聚合 clause_path_norm)+ 真 dict_violation_types 加载 +
    dict_version 取自真 seed;fake LLM(无需 key)。验装配把 L2 写进 case fields。
    """
    _cfg, pg, ctx = pg_ctx
    vts = {v.name: v.dict_version for v in pg.get_violation_types()}
    if not vts:
        pytest.skip("dict_violation_types 未 seed(先 demo up/seed)")
    target = next(iter(vts))  # 取真字典首项作 fake 命中,验真 dict 加载 + 版本回填

    doc_no = "〔2099〕测试99号"
    fields = {"violation_category": None, "cited_regulations": [], "ref_unresolved": False}
    with _seeded_ext_reg(pg, doc_no, "测试外规办法", "2/15"):
        client = FakeClient(
            _route(
                cited=[{"title": "测试外规办法", "doc_number": doc_no, "clause": "第十五条"}],
                violation=target,
            )
        )
        case_l2.apply(ctx, "案情", fields, client=client)

    # 真 PgRegLookup 按文号命中 + 条号归一对齐到 clause_path_norm
    assert fields["cited_regulations"] == [
        {
            "doc_number": doc_no,
            "title": "测试外规办法",
            "clause_path_norm": "2/15",
            "resolved": True,
        }
    ]
    assert fields["ref_unresolved"] is False
    # 违规事由来自真字典 + dict_version 取自真 seed
    assert fields["violation_category"] == target
    assert fields["violation_category_dict_version"] == vts[target]


def test_case_l2_real_model_chain_and_dict_constraint(pg_ctx):
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY 未设置——案例 L2 真模型门控集成测跳过(绝不联网)")
    from pipeline.llm_client import make_llm_client

    _cfg, pg, ctx = pg_ctx
    allowed = {v.name for v in pg.get_violation_types()}
    if not allowed:
        pytest.skip("dict_violation_types 未 seed(先 demo up/seed)")

    doc_no = "〔2099〕测试99号"
    fields = {"violation_category": None, "cited_regulations": [], "ref_unresolved": False}
    with _seeded_ext_reg(pg, doc_no, "测试外规办法", "15"):
        case_text = (
            "当事人:某证券公司。经查,当事人未按规定披露重大信息。"
            f"依据《测试外规办法》({doc_no})第十五条,我会决定对其予以警告。"
        )
        case_l2.apply(ctx, case_text, fields, client=make_llm_client())  # 真链路不抛 = 通

    # dict 约束对真模型生效:违规事由要么 None 要么落在字典内
    assert fields["violation_category"] is None or fields["violation_category"] in allowed
    # cited_regulations 形态正确;每条 resolved 项确有 clause_path_norm
    assert isinstance(fields["cited_regulations"], list)
    for r in fields["cited_regulations"]:
        assert set(r) == {"doc_number", "title", "clause_path_norm", "resolved"}
        if r["resolved"]:
            assert r["clause_path_norm"]
