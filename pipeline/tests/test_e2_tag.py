"""E2 条款级 LLM 打标:纯助手单元(免栈、免 LLM,注入 fake)+ run_e2 集成(连 PG,免真 LLM)。

**绝不发真 OpenAI 请求**:所有用例注入 ``FakeClient``,其 ``chat_json`` 返回预置 dict(零网络、
无 API key)。默认关用例断言 ``e2_enabled=False`` 时 _structuring 不构造 client、不发任何 LLM 调用。
"""

import pytest
from sqlalchemy import delete, select, text
from ulid import ULID

from common.pg_models import Chunk, ClauseTag, Document, DocVersion, ImportBatch
from pipeline import cli
from pipeline.config import load_config
from pipeline.enrich import e2_tag as e2
from pipeline.index.object_store import ObjectStore
from pipeline.index.pg_io import PgIO
from pipeline.stage_base import StageContext


class FakeClient:
    """注入式假 LLM:记调用数,按 chunk 文本返回预置 dict(零网络、无 key)。"""

    def __init__(self, responses: dict[str, dict] | None = None, default: dict | None = None):
        self._responses = responses or {}
        self._default = default if default is not None else {
            "entity_type": [], "departments": [], "matters": []
        }
        self.calls = 0

    def chat_json(self, system: str, user: str) -> dict:
        self.calls += 1
        for key, resp in self._responses.items():
            if key in user:
                return resp
        return self._default


# ── 单元:build_e2_prompt(含名单 + JSON / 不臆测指令)──────────────────
def test_build_e2_prompt_includes_names_and_rules():
    system, user = e2.build_e2_prompt(
        "第三条 营业部应当报告",
        ["A类营业部", "证券营业部"],
        ["合规部"],
        ["信息披露"],
    )
    # 字典约束 + 不臆测在 system
    assert "严格来自" in system and "不臆测" in system
    assert "JSON" in system
    # 三份允许清单全进 user
    assert "A类营业部" in user and "证券营业部" in user
    assert "合规部" in user and "信息披露" in user
    # 待打标条文 + JSON 形状指令
    assert "营业部应当报告" in user
    assert "entity_type" in user and "departments" in user and "matters" in user
    assert "不臆测" in user


def test_build_e2_prompt_empty_lists_render_placeholder():
    _system, user = e2.build_e2_prompt("条文", [], [], [])
    assert "(空)" in user


# ── 单元:tag_chunk 服务端字典裁剪(out-of-dict 丢弃,never trust LLM)──────
def test_tag_chunk_drops_out_of_dict_values():
    dicts = e2.E2Dicts(
        entity_types={"A类营业部": "v0", "证券营业部": "v0"},
        departments={"合规部": "v0"},
        matters={"信息披露": "n/a"},
    )
    # LLM 返回:1 合法实体 + 1 非法实体(字典外)+ 合法部门 + 非法事项
    client = FakeClient(default={
        "entity_type": ["A类营业部", "火星营业部"],
        "departments": ["合规部"],
        "matters": ["臆造事项"],
    })
    out = e2.tag_chunk(client, "任意条文", dicts)
    assert out["entity_type"] == ["A类营业部"]  # 字典外 火星营业部 被丢
    assert out["departments"] == ["合规部"]
    assert out["matters"] == []  # 臆造事项 字典外 → 空


def test_tag_chunk_handles_non_list_and_dedup():
    dicts = e2.E2Dicts(
        entity_types={"A类营业部": "v0"}, departments={"合规部": "v0"}, matters={"信息披露": "n/a"}
    )
    client = FakeClient(default={
        "entity_type": "不是列表",  # 非 list → 空
        "departments": ["合规部", "合规部", "不存在"],  # 去重 + 裁字典
        "matters": None,
    })
    out = e2.tag_chunk(client, "条文", dicts)
    assert out["entity_type"] == []
    assert out["departments"] == ["合规部"]
    assert out["matters"] == []


# ── 集成:run_e2 写入 + 幂等 + E1 不受扰(连 PG,免真 LLM)──────────────
@pytest.fixture
def pg_ctx():
    cfg = load_config()
    pg = PgIO.from_config(cfg)
    try:
        with pg.session() as s:
            s.execute(text("select 1"))
    except Exception:
        pytest.skip("PG 不可达")
    yield pg, StageContext(config=cfg, object_store=ObjectStore.from_config(cfg), db=pg)


@pytest.fixture
def seeded(pg_ctx):
    pg, ctx = pg_ctx
    bid, lid, dvid = "e2_" + str(ULID()), str(ULID()), str(ULID())
    # 2 条款非 parent + 1 parent(不打标)
    specs = [
        ("第一条 营业部应当披露重大事项", False),
        ("第二条 一般规定", False),
        ("第一章 总则", True),
    ]
    with pg.session() as s:
        s.add(ImportBatch(batch_id=bid, source_dir="x"))
        s.add(Document(logical_id=lid, corpus_type="P-INT"))
        s.flush()
        s.add(
            DocVersion(
                doc_version_id=dvid, logical_id=lid, batch_id=bid, source_format="docx",
                source_hash="h" + dvid[:8], raw_object_key="k", pipeline_status="META_REVIEW",
                perm_tag="内部", biz_domain="X", issuer="CSRC",
            )
        )
        s.flush()
        for i, (txt, parent) in enumerate(specs):
            s.add(
                Chunk(
                    chunk_id=(f"e2c{i}" + dvid)[:24], doc_version_id=dvid, text=txt,
                    clause_path=str(i), clause_path_norm=str(i), seq=i, page_start=1,
                    is_parent=parent, is_table=False, chunk_status="effective",
                )
            )
    yield pg, ctx, dvid
    with pg.session() as s:
        ids = list(s.scalars(select(Chunk.chunk_id).where(Chunk.doc_version_id == dvid)))
        if ids:
            s.execute(delete(ClauseTag).where(ClauseTag.chunk_id.in_(ids)))
        s.execute(delete(Chunk).where(Chunk.doc_version_id == dvid))
        s.execute(delete(DocVersion).where(DocVersion.doc_version_id == dvid))
        s.execute(delete(Document).where(Document.logical_id == lid))
        s.execute(delete(ImportBatch).where(ImportBatch.batch_id == bid))


def _e2_tags(pg, dvid):
    with pg.session() as s:
        ids = list(s.scalars(select(Chunk.chunk_id).where(Chunk.doc_version_id == dvid)))
        return list(
            s.scalars(
                select(ClauseTag).where(
                    ClauseTag.chunk_id.in_(ids),
                    ClauseTag.tag_type.in_(["e2_entity_type", "department", "matter"]),
                )
            )
        )


def _fake_for_dicts(ctx):
    """取库内真字典首项,造一个对「披露」条文打标、对其它条文留空的 fake client。"""
    ents = [d.name for d in ctx.db.get_entity_types()]
    depts = [d.name for d in ctx.db.get_departments()]
    matters = [d.name for d in ctx.db.get_biz_domains()]
    assert ents and depts and matters, "字典未 seed(先 demo up/seed)"
    # key 取「第一条」(仅目标 chunk 文本含,字典名单不含)→ 不被「待打标条文」外的清单文字误匹配
    return FakeClient(
        responses={
            "第一条": {
                "entity_type": [ents[0], "字典外实体"],  # 含非法值 → 服务端裁掉
                "departments": [depts[0]],
                "matters": [matters[0]],
            }
        },
        default={"entity_type": [], "departments": [], "matters": []},
    ), ents[0], depts[0], matters[0]


def test_run_e2_writes_entity_dept_matter(seeded):
    pg, ctx, dvid = seeded
    client, ent0, dept0, matter0 = _fake_for_dicts(ctx)
    r = e2.run_e2(ctx, dvid, client=client)
    assert r.total == 2  # 非 parent 块
    assert r.tagged == 1  # 仅「披露」块命中,「一般规定」留空
    assert client.calls == 2  # 每非 parent 块各调一次,parent 不调

    tags = _e2_tags(pg, dvid)
    by_type = {}
    for t in tags:
        by_type.setdefault(t.tag_type, []).append(t)
    # 实体类型写进 JSONB 列(裁掉字典外值)
    ent_rows = by_type["e2_entity_type"]
    assert len(ent_rows) == 1
    assert ent_rows[0].entity_type == [ent0]
    assert "字典外实体" not in (ent_rows[0].entity_type or [])
    assert ent_rows[0].evidence  # dict_version 快照
    # 部门 / 事项各一行,tag_value=名,evidence=dict_version
    assert [t.tag_value for t in by_type["department"]] == [dept0]
    assert [t.tag_value for t in by_type["matter"]] == [matter0]


def test_run_e2_idempotent_rerun(seeded):
    pg, ctx, dvid = seeded
    client, *_ = _fake_for_dicts(ctx)
    e2.run_e2(ctx, dvid, client=client)
    first = {(t.tag_type, t.tag_value, t.chunk_id) for t in _e2_tags(pg, dvid)}
    # 重跑:run_e2 内含 clear → 不重复
    client2, *_ = _fake_for_dicts(ctx)
    e2.run_e2(ctx, dvid, client=client2)
    second = {(t.tag_type, t.tag_value, t.chunk_id) for t in _e2_tags(pg, dvid)}
    assert first == second
    # 总行数不翻倍
    assert len(_e2_tags(pg, dvid)) == len(first)


def test_run_e2_clear_does_not_touch_e1(seeded):
    pg, ctx, dvid = seeded
    # 先写一条 E1 is_obligation 行 + 一条 duration 行
    cid = pg.get_chunks(dvid)[0].chunk_id
    with pg.session() as s:
        s.add(ClauseTag(chunk_id=cid, tag_type="is_obligation", tag_value="true", evidence="应当"))
        s.add(ClauseTag(chunk_id=cid, tag_type="duration", tag_value="parsed", evidence="九十日"))
    client, *_ = _fake_for_dicts(ctx)
    e2.run_e2(ctx, dvid, client=client)  # 内含 E2 clear
    # E1 行仍在
    with pg.session() as s:
        ids = list(s.scalars(select(Chunk.chunk_id).where(Chunk.doc_version_id == dvid)))
        e1_rows = list(
            s.scalars(
                select(ClauseTag).where(
                    ClauseTag.chunk_id.in_(ids),
                    ClauseTag.tag_type.in_(["is_obligation", "duration"]),
                )
            )
        )
    assert {r.tag_type for r in e1_rows} == {"is_obligation", "duration"}


# ── T1.1 真模型门控集成:有 OPENAI_API_KEY 才跑(绝不联网),验真链路 + 字典约束对真模型生效 ──
def test_run_e2_real_model_stays_in_dict(seeded):
    import os

    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY 未设置——E2 真模型门控集成测跳过(绝不联网)")
    from pipeline.llm_client import make_llm_client

    pg, ctx, dvid = seeded
    allowed_ents = {d.name for d in ctx.db.get_entity_types()}
    allowed_depts = {d.name for d in ctx.db.get_departments()}
    allowed_matters = {d.name for d in ctx.db.get_biz_domains()}
    client = make_llm_client()  # 端点/模型由 env(OPENAI_API_KEY/BASE_URL/MODEL)配置,端点无关
    r = e2.run_e2(ctx, dvid, client=client)  # 真 LLM 端到端(不抛 = 真链路通)
    assert r.total == 2  # 2 非 parent 块都过真模型
    # 服务端字典约束对真模型生效:任何落库值都在字典内(LLM 越界值被 _enforce 裁掉)
    for t in _e2_tags(pg, dvid):
        if t.tag_type == "e2_entity_type":
            assert set(t.entity_type or []) <= allowed_ents
        elif t.tag_type == "department":
            assert t.tag_value in allowed_depts
        elif t.tag_type == "matter":
            assert t.tag_value in allowed_matters


# ── 装配:_structuring 默认关 → 零 LLM(不构造 client、不调用)──────────────
@pytest.fixture
def cfg_ctx():
    return StageContext(config=load_config())  # 仅 config;s3/s4/e1/e2 被 monkeypatch


def test_structuring_e2_disabled_no_llm_call(cfg_ctx, monkeypatch):
    calls: list[str] = []
    sentinel = object()
    monkeypatch.setattr(cli.s3_structure, "run", lambda c, d: calls.append("s3"))
    monkeypatch.setattr(cli.s4_meta, "run", lambda c, d: (calls.append("s4"), sentinel)[1])

    # make_llm_client 若被构造则炸 → 证明默认关路径绝不触达 LLM
    def boom(*a, **k):
        raise AssertionError("默认关不应构造 LLM client")

    monkeypatch.setattr(cli.e2_tag, "make_llm_client", boom)
    cfg_ctx.config.toggles.e1_enabled = False
    cfg_ctx.config.toggles.e2_enabled = False
    out = cli._structuring(cfg_ctx, "dv")
    assert calls == ["s3", "s4"]  # 关 e2:不调 run_e2
    assert out is sentinel


def test_structuring_e2_enabled_runs_after_s3(cfg_ctx, monkeypatch):
    calls: list[str] = []
    sentinel = object()
    monkeypatch.setattr(cli.s3_structure, "run", lambda c, d: calls.append("s3"))
    monkeypatch.setattr(cli.s4_meta, "run", lambda c, d: (calls.append("s4"), sentinel)[1])
    monkeypatch.setattr(cli.e2_tag, "clear", lambda c, d: calls.append("e2-clear"))
    monkeypatch.setattr(cli.e2_tag, "run_e2", lambda c, d: calls.append("e2-run"))
    cfg_ctx.config.toggles.e1_enabled = False
    cfg_ctx.config.toggles.e2_enabled = True
    out = cli._structuring(cfg_ctx, "dv")
    assert calls == ["e2-clear", "s3", "e2-run", "s4"]  # clear 先于 s3;run 在 s3 后
    assert out is sentinel


def test_structuring_e2_exception_nonblocking(cfg_ctx, monkeypatch):
    calls: list[str] = []
    sentinel = object()
    monkeypatch.setattr(cli.s3_structure, "run", lambda c, d: calls.append("s3"))
    monkeypatch.setattr(cli.s4_meta, "run", lambda c, d: (calls.append("s4"), sentinel)[1])
    monkeypatch.setattr(cli.e2_tag, "clear", lambda c, d: None)

    def boom(c, d):
        calls.append("e2-boom")
        raise RuntimeError("E2 炸了")

    monkeypatch.setattr(cli.e2_tag, "run_e2", boom)
    cfg_ctx.config.toggles.e1_enabled = False
    cfg_ctx.config.toggles.e2_enabled = True
    out = cli._structuring(cfg_ctx, "dv")  # run_e2 抛错被 _safe_e2 吞
    assert out is sentinel  # 不阻断终态
    assert "e2-boom" in calls and "s4" in calls
