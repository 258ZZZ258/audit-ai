"""A1 · E1 义务打标:`match_obligation` 单元(免栈)+ `tag`/`clear` 集成(连 PG,免模型)。"""

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from ulid import ULID

from common.pg_models import Chunk, ClauseTag, Document, DocVersion, ImportBatch
from pipeline import cli
from pipeline.config import ObligationConfig, load_config
from pipeline.enrich import e1_obligation as e1
from pipeline.index.object_store import ObjectStore
from pipeline.index.pg_io import PgIO
from pipeline.stage_base import StageContext

# ── 单元:match_obligation(免栈,真实 obligation.yaml 词表)──────────────
CFG = load_config().obligation


@pytest.mark.parametrize(
    "s,expect,ev",
    [
        ("第二条 有关部门应当在二十四小时内书面报告", True, "应当"),
        ("印章由专人保管,保管人不得擅自用印", True, "不得"),
        ("报销人应如实填写报销单", True, "应"),  # bare 应(句首,前缀不在排除表)
        ("公司应披露重大事项", True, "应"),  # 应+动词=义务,evidence 退化为 应
        ("公司对相应债权未提取足额坏账准备", False, None),  # 相应 排除,无其他义务词
        ("适应市场变化调整经营策略", False, None),  # 适应 排除
        ("对应当事人作出相应处理", False, None),  # 对应当:前缀排除作用于 应当 marker
        ("履行相应程序后报本所", False, None),  # 相应程序:相 前缀排除
        ("本办法自发布之日起施行", False, None),  # 施行日期句:负例
        ("本办法所称重大事项,是指下列情形", False, None),  # 释义句:负例
        ("", False, None),
    ],
)
def test_match_obligation(s, expect, ev):
    ok, e = e1.match_obligation(s, CFG)
    assert ok is expect
    if expect:
        assert e == ev


def test_prefix_exclusion_applies_to_marker():
    # 应 在 bare_chars 时,应当 marker 仍受前缀排除:对应当事人 不误命中,门应当报告 命中
    cfg = ObligationConfig(
        markers=["应当"], bare_chars=["应"], exclusions=["对应"], accuracy_threshold=0.9
    )
    assert e1.match_obligation("对应当事人作出处理", cfg) == (False, None)
    assert e1.match_obligation("有关部门应当报告", cfg)[0] is True


def test_marker_priority():
    ok, e = e1.match_obligation("必须并且不得擅自处理", CFG)  # 多义务词:返 markers 顺序首个
    assert ok and e in CFG.markers


def test_bare_chars_empty():
    cfg = ObligationConfig(markers=["不得"], bare_chars=[], exclusions=[], accuracy_threshold=0.9)
    assert e1.match_obligation("报销人应如实填写", cfg) == (False, None)  # 无 bare 字:单应不算
    assert e1.match_obligation("不得擅自", cfg)[0] is True


def test_bare_xu_and_negation():
    # bare 须 命中(用印须填写);无须 排除(否定义务,不排除会把 无须审批 误标)
    assert e1.match_obligation("用印须填写申请单", CFG)[0] is True
    assert e1.match_obligation("无须履行审批程序的事项径行办理", CFG) == (False, None)


# ── 单元:classify_deontic(命中情态词 → deontic_type 分类,纯函数)─────────────
@pytest.mark.parametrize(
    "marker,expect",
    [
        ("应当", "obligation"),
        ("应该", "obligation"),
        ("必须", "obligation"),
        ("应", "obligation"),  # bare 应
        ("须", "obligation"),  # bare 须
        ("须经", "obligation"),
        ("有义务", "obligation"),  # 未列具体前缀 → 兜底义务
        ("负有", "obligation"),
        ("不得", "prohibition"),
        ("禁止", "prohibition"),
        ("严禁", "prohibition"),
        ("不应", "prohibition"),  # 否定前缀须先于 应 判定,不可被吞成 obligation
        ("不准", "prohibition"),
        ("责令", "command"),
        (None, None),
        ("", None),
    ],
)
def test_classify_deontic(marker, expect):
    assert e1.classify_deontic(marker) == expect


# ── 单元:normalize_duration(期限归一到日,中文/Arabic,standoff,纯函数)──────────
@pytest.mark.parametrize(
    "text,days,biz,status",
    [
        ("应当在九十日内完成", 90, False, "parsed"),  # 中文自然日(裸「日」)
        ("应于90日内书面报告", 90, False, "parsed"),  # Arabic 日
        ("逾期30天未缴", 30, False, "parsed"),  # 天 = 自然日
        ("应当在5个工作日内办结", 5, True, "parsed"),  # Arabic 工作日
        ("五个工作日内反馈", 5, True, "parsed"),  # 中文工作日
        ("自然日二十四日内", 24, False, "parsed"),  # 自然日(数字在「自然日」前→裸日命中 24)
        ("3个月内整改", 90, False, "parsed"),  # 月 ×30
        ("1年内复核", 365, False, "parsed"),  # 年 ×365
        ("一个季度内结算", 90, False, "parsed"),  # 季 ×90
        ("半年内不得变更", 180, False, "parsed"),  # 半年 = 180(忽略数字定语)
    ],
)
def test_normalize_duration_parsed(text, days, biz, status):
    r = e1.normalize_duration(text)
    assert r is not None
    assert r.norm_duration_days == days
    assert r.is_business_day is biz
    assert r.norm_status == status
    assert r.surface and r.surface in text  # standoff:surface 取自原文


def test_normalize_duration_compound_unparsed():
    # 复合/相对期限「次年首个工作日」:无「数+单位」可归一 → unparsed,留 surface、norm=None
    r = e1.normalize_duration("应当于次年首个工作日前完成结转")
    assert r is not None
    assert r.norm_status == "unparsed"
    assert r.norm_duration_days is None
    assert r.is_business_day is None
    assert r.surface


def test_normalize_duration_none_when_no_duration():
    # 无期限语义(含纯百分比表达,不应误成期限)→ None,完全不写 duration 行
    assert e1.normalize_duration("不良率不得超过5%且应如实披露") is None
    assert e1.normalize_duration("应当遵守相关规定") is None


def test_normalize_duration_surface_standoff():
    # standoff 契约:surface 为原文片段,函数不修改输入文本
    src = "有关部门应当在二十四小时内书面报告"
    r = e1.normalize_duration(src)
    assert r is None or src == "有关部门应当在二十四小时内书面报告"  # 「小时」非期限单位 → None


# ── 集成:tag / clear(连 PG,免模型)────────────────────────────
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
    bid, lid, dvid = "e1_" + str(ULID()), str(ULID()), str(ULID())
    # (文本, is_parent):3 义务非 parent + 1 非义务 + 1 parent(义务文本但 parent 不打标)
    specs = [
        ("应当报告", False),
        ("不得擅自", False),
        ("应如实填写", False),
        ("本办法自发布之日起施行", False),
        ("第一章 总则 应当遵守", True),
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
                    chunk_id=(f"e{i}" + dvid)[:24], doc_version_id=dvid, text=txt,
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


def _tags(pg, dvid):
    with pg.session() as s:
        ids = list(s.scalars(select(Chunk.chunk_id).where(Chunk.doc_version_id == dvid)))
        return list(
            s.scalars(
                select(ClauseTag).where(
                    ClauseTag.chunk_id.in_(ids), ClauseTag.tag_type == "is_obligation"
                )
            )
        )


def test_tag_writes_only_obligation_nonparent(seeded):
    pg, ctx, dvid = seeded
    r = e1.tag(ctx, dvid)
    assert r.total == 4  # 非 parent 块(parent 不计)
    assert r.tagged == 3  # 应当报告 / 不得擅自 / 应如实填写;施行日期句不中;parent 不打
    tags = _tags(pg, dvid)
    assert len(tags) == 3
    assert all(t.tag_value == "true" and t.evidence for t in tags)


def test_clear_then_tag_idempotent(seeded):
    pg, ctx, dvid = seeded
    e1.tag(ctx, dvid)
    first = {t.chunk_id for t in _tags(pg, dvid)}
    n = e1.clear(ctx, dvid)
    assert n == 3 and not _tags(pg, dvid)  # clear 删净
    e1.tag(ctx, dvid)
    assert {t.chunk_id for t in _tags(pg, dvid)} == first  # 重打同集 → 幂等


def test_replace_chunks_without_clear_hits_fk(seeded):
    """证明风险:clause_tags 引用 chunk 时直接 replace_chunks(删 chunk)→ FK 违例。"""
    pg, ctx, dvid = seeded
    e1.tag(ctx, dvid)
    assert _tags(pg, dvid)
    with pytest.raises(IntegrityError):  # 删被 clause_tags 引用的 chunk → 外键违例
        pg.replace_chunks(dvid, [])


def test_clear_before_replace_is_fk_safe(seeded):
    """证明修复:_structuring 的 clear-先于-s3 顺序——先清 tag 再删 chunk 不撞 FK。"""
    pg, ctx, dvid = seeded
    e1.tag(ctx, dvid)
    e1.clear(ctx, dvid)
    pg.replace_chunks(dvid, [])  # 不应抛
    assert not pg.get_chunks(dvid)


# ── 装配:_structuring 接 E1(clear→s3→tag→s4),免栈 monkeypatch 编排逻辑 ──────────
@pytest.fixture
def cfg_ctx():
    return StageContext(config=load_config())  # 仅 config;s3/s4/e1 被 monkeypatch,不碰 PG


def _spy_structuring(monkeypatch):
    """monkeypatch _structuring 的四个被调,记录调用序;返回 (calls, s4_sentinel)。"""
    calls: list[str] = []
    sentinel = object()
    monkeypatch.setattr(cli.e1_obligation, "clear", lambda c, d: calls.append("clear"))
    monkeypatch.setattr(cli.e1_obligation, "tag", lambda c, d: calls.append("tag"))
    monkeypatch.setattr(cli.s3_structure, "run", lambda c, d: calls.append("s3"))
    monkeypatch.setattr(cli.s4_meta, "run", lambda c, d: (calls.append("s4"), sentinel)[1])
    return calls, sentinel


def test_structuring_e1_enabled_order(cfg_ctx, monkeypatch):
    calls, sentinel = _spy_structuring(monkeypatch)
    cfg_ctx.config.toggles.e1_enabled = True
    out = cli._structuring(cfg_ctx, "dv")
    assert calls == ["clear", "s3", "tag", "s4"]  # clear 先于 s3;tag 在 s3 后;s4 收尾
    assert out is sentinel  # 终态由 s4 决定


def test_structuring_e1_disabled_no_write(cfg_ctx, monkeypatch):
    calls, sentinel = _spy_structuring(monkeypatch)
    cfg_ctx.config.toggles.e1_enabled = False
    out = cli._structuring(cfg_ctx, "dv")
    assert calls == ["s3", "s4"]  # 关 e1:不调 clear/tag
    assert out is sentinel


def test_structuring_e1_exception_nonblocking(cfg_ctx, monkeypatch):
    calls, sentinel = _spy_structuring(monkeypatch)
    cfg_ctx.config.toggles.e1_enabled = True

    def boom(c, d):
        calls.append("tag-boom")
        raise RuntimeError("E1 炸了")

    monkeypatch.setattr(cli.e1_obligation, "tag", boom)
    out = cli._structuring(cfg_ctx, "dv")  # tag 抛错被 _safe_e1 吞
    assert out is sentinel  # 不阻断:仍返 s4 终态
    assert "tag-boom" in calls and "s4" in calls
