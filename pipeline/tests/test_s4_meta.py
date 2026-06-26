"""s4_meta 集成测试(连真 PG + tmp ObjectStore;PG 不可达 skip)。"""

from datetime import date

import pytest
from sqlalchemy import delete, select, text
from ulid import ULID

from common.ir import Block, BlockType, IRDocument, SourceFormat
from common.pg_models import (
    Case,
    Document,
    DocVersion,
    ImportBatch,
    PipelineEvent,
    ReviewQueue,
)
from pipeline.config import load_config
from pipeline.index.object_store import ObjectStore
from pipeline.index.pg_io import PgIO
from pipeline.stage_base import StageContext
from pipeline.stages import s4_meta as s4
from pipeline.states import PipelineState as PS


@pytest.fixture
def pg():
    io = PgIO.from_config(load_config())
    try:
        with io.session() as s:
            s.execute(text("select 1"))
    except Exception:
        pytest.skip("PG 不可达(demo up 未起)")
    return io


@pytest.fixture
def env(pg, tmp_path):
    ctx = StageContext(config=load_config(), object_store=ObjectStore(tmp_path / "obj"), db=pg)
    bids: list[str] = []
    yield ctx, bids
    with pg.session() as s:
        flt = DocVersion.batch_id.in_(bids or [""])
        dvids = list(s.scalars(select(DocVersion.doc_version_id).where(flt)))
        lids = list(s.scalars(select(DocVersion.logical_id).where(flt)))
        if dvids:
            s.execute(delete(ReviewQueue).where(ReviewQueue.doc_version_id.in_(dvids)))
            s.execute(delete(PipelineEvent).where(PipelineEvent.doc_version_id.in_(dvids)))
            s.execute(delete(Case).where(Case.doc_version_id.in_(dvids)))
            s.execute(delete(DocVersion).where(DocVersion.doc_version_id.in_(dvids)))
        if lids:
            s.execute(delete(Document).where(Document.logical_id.in_(lids)))
        if bids:
            s.execute(delete(ImportBatch).where(ImportBatch.batch_id.in_(bids)))


def _seed(ctx, bids, *, doc_number, issue_date, title, supersedes=None, corpus="P-INT",
          biz_domain=None) -> str:
    """落 doc(STRUCTURING,带 manifest 字段)+ put_ir(版头含 京证监〔2024〕5号 / 2024年1月1日)。

    ``supersedes``:置 supersedes_version_id(模拟修订件;B-严 据此把修订件挡回 META_REVIEW)。
    ``corpus``:Document.corpus_type(T2.3b 业务域 L2 profile 分档按之分档)。
    ``biz_domain``:manifest 单值业务域(T2.3b manifest 优先/冲突路径)。
    """
    bid, lid, dvid = "s4_" + str(ULID()), str(ULID()), str(ULID())
    bids.append(bid)
    p = BlockType.PARAGRAPH
    ir = IRDocument(
        doc_version_id=dvid, source_format=SourceFormat.DOCX, title=title,
        blocks=[
            Block(index=0, type=p, text="京证监〔2024〕5号", page=1),
            Block(index=1, type=p, text="2024年1月1日", page=1),
            Block(index=2, type=p, text="第一条 略。", page=1),
        ],
    )
    ctx.db.add(ImportBatch(batch_id=bid, source_dir="x"))
    ctx.db.add(Document(logical_id=lid, corpus_type=corpus))
    ctx.db.add(
        DocVersion(
            doc_version_id=dvid, logical_id=lid, batch_id=bid, source_format="docx",
            source_hash="h" + dvid[:8], raw_object_key="k", pipeline_status=PS.STRUCTURING.value,
            doc_number=doc_number, issue_date=issue_date, title=title,
            supersedes_version_id=supersedes, biz_domain=biz_domain,
        )
    )
    ctx.object_store.put_ir(ir)
    return dvid


def _ctx_with_toggle(ctx, *, auto_confirm: bool) -> StageContext:
    toggles = ctx.config.toggles.model_copy(update={"auto_confirm_meta_no_conflict": auto_confirm})
    return StageContext(
        config=ctx.config.model_copy(update={"toggles": toggles}),
        object_store=ctx.object_store,
        db=ctx.db,
    )


def _ctx_l2(ctx, *, auto_confirm: bool = True) -> StageContext:
    """开 l2_enabled(+ auto_confirm):验业务域 L2 待确认能否阻自动放行。"""
    toggles = ctx.config.toggles.model_copy(
        update={"l2_enabled": True, "auto_confirm_meta_no_conflict": auto_confirm}
    )
    return StageContext(
        config=ctx.config.model_copy(update={"toggles": toggles}),
        object_store=ctx.object_store,
        db=ctx.db,
    )


class _FakeBizClient:
    """注入式假 LLM:chat_json 恒返回预置 biz_domains(零网络、无 key)。"""

    def __init__(self, biz_names):
        self._biz = biz_names

    def chat_json(self, system, user):
        return {"biz_domains": self._biz}


def test_consistent_meta_enqueues_routine_confirm(env):
    # A 模式(关自动放行):无冲突件也入 meta_confirm 队列(META_REVIEW 全件强制人工闸)。
    ctx, bids = env
    ctx = _ctx_with_toggle(ctx, auto_confirm=False)
    dvid = _seed(
        ctx, bids, doc_number="京证监〔2024〕5号", issue_date=date(2024, 1, 1), title="某办法"
    )
    res = s4.run(ctx, dvid)
    assert res.next_state is PS.META_REVIEW
    assert res.queue is not None and res.queue.queue_type == "meta_confirm"
    assert res.queue.evidence["conflicts"] == []  # 无冲突:常规确认


def test_consistent_meta_auto_confirms_when_enabled(env):
    # B 模式:无冲突的**全新件**(无 supersedes)自动放行 → EMBEDDING。
    ctx, bids = env
    ctx = _ctx_with_toggle(ctx, auto_confirm=True)
    dvid = _seed(
        ctx, bids, doc_number="京证监〔2024〕5号", issue_date=date(2024, 1, 1), title="某办法"
    )
    res = s4.run(ctx, dvid)
    assert res.next_state is PS.EMBEDDING
    assert res.queue is None
    assert res.evidence == {"conflicts": [], "auto_confirmed": True}


def test_revision_stays_gated_even_when_auto_confirm_enabled(env):
    # B-严:带 supersedes 的修订件即便无冲突、即便开关开,仍进 META_REVIEW
    #(supersede 旧版是最有后果的权威变更,须有人点头)。
    ctx, bids = env
    ctx = _ctx_with_toggle(ctx, auto_confirm=True)
    dvid = _seed(
        ctx, bids, doc_number="京证监〔2024〕5号", issue_date=date(2024, 1, 1),
        title="某办法", supersedes=str(ULID()),
    )
    res = s4.run(ctx, dvid)
    assert res.next_state is PS.META_REVIEW
    assert res.queue is not None and res.queue.queue_type == "meta_confirm"
    assert res.queue.evidence["conflicts"] == []  # 无冲突,但因是修订件仍入闸
    assert "修订" in res.queue.reason


def test_conflict_enqueues_meta_confirm(env):
    ctx, bids = env
    # manifest 文号与 IR(京证监〔2024〕5号)不符 → 冲突
    dvid = _seed(
        ctx, bids, doc_number="京证监〔2024〕9号", issue_date=date(2024, 1, 1), title="某办法"
    )
    res = s4.run(ctx, dvid)
    assert res.next_state is PS.META_REVIEW  # 仍过闸,另入队
    assert res.queue is not None and res.queue.queue_type == "meta_confirm"
    fields = [c["field"] for c in res.queue.evidence["conflicts"]]
    assert "doc_number" in fields


def _seed_case(ctx, bids) -> str:
    """落 P-CASE 决定书(STRUCTURING)+ put_ir(头部机构 + 文号 + 当事人 + 金额 + 落款日期)。"""
    bid, lid, dvid = "s4_" + str(ULID()), str(ULID()), str(ULID())
    bids.append(bid)
    p = BlockType.PARAGRAPH
    ir = IRDocument(
        doc_version_id=dvid, source_format=SourceFormat.DOCX, title="某某行政处罚决定书",
        blocks=[
            Block(index=0, type=p, text="北京证监局", page=1),
            Block(index=1, type=p, text="京证监〔2024〕5号", page=1),
            Block(index=2, type=p, text="当事人:某某证券有限公司,住所地北京市。", page=1),
            Block(index=3, type=p, text="经查,该公司存在违规行为。", page=1),
            Block(index=4, type=p, text="现决定:对当事人处以罚款50万元。", page=1),
            Block(index=5, type=p, text="2024年3月15日", page=1),
        ],
    )
    ctx.db.add(ImportBatch(batch_id=bid, source_dir="x"))
    ctx.db.add(Document(logical_id=lid, corpus_type="P-CASE"))
    ctx.db.add(
        DocVersion(
            doc_version_id=dvid, logical_id=lid, batch_id=bid, source_format="docx",
            source_hash="h" + dvid[:8], raw_object_key="k", pipeline_status=PS.STRUCTURING.value,
            issuer="北京证监局", title="某某行政处罚决定书",
        )
    )
    ctx.object_store.put_ir(ir)
    return dvid


def test_pcase_s4_writes_case_row(env):
    # P-CASE 件经 s4 后写一行 cases(规则抽取);P-INT/P-EXT/P-QA 不写。
    # 常规闸行为不变:无冲突无 supersedes 件按 config 默认(auto_confirm)放行 EMBEDDING。
    ctx, bids = env
    dvid = _seed_case(ctx, bids)
    res = s4.run(ctx, dvid)
    assert res.next_state in (PS.EMBEDDING, PS.META_REVIEW)  # 案例抽取不改 s4 闸语义
    row = ctx.db.get_case(dvid)
    assert row is not None
    assert row.penalty_org == "北京证监局"
    assert row.doc_number == "京证监[2024]5号"
    assert row.penalty_date == date(2024, 3, 15)
    assert row.respondent == "某某证券有限公司" and row.respondent_type == "机构"
    assert row.amount_wan == 50.0
    assert "罚款" in row.penalty_type
    # L2 字段留空
    assert row.violation_category is None and row.cited_regulations == []
    assert row.ref_unresolved is False


def test_pint_s4_writes_no_case_row(env):
    # P-INT 件 s4 不触 cases 表(P-INT/P-EXT/P-QA 行为不变)。
    ctx, bids = env
    dvid = _seed(
        ctx, bids, doc_number="京证监〔2024〕5号", issue_date=date(2024, 1, 1), title="某办法"
    )
    s4.run(ctx, dvid)
    assert ctx.db.get_case(dvid) is None


def test_upsert_case_get_case_round_trip(env):
    # pg_io.upsert_case/get_case 直连 PG 往返(upsert 覆盖安全)。
    ctx, bids = env
    dvid = _seed_case(ctx, bids)
    ctx.db.upsert_case(dvid, {"penalty_org": "甲局", "amount_wan": 10.0, "respondent_type": "个人"})
    row = ctx.db.get_case(dvid)
    assert row.penalty_org == "甲局" and row.amount_wan == 10.0
    # 再次 upsert 覆盖(merge 幂等)
    ctx.db.upsert_case(dvid, {"penalty_org": "乙局", "amount_wan": 20.0})
    row2 = ctx.db.get_case(dvid)
    assert row2.penalty_org == "乙局" and row2.amount_wan == 20.0


# ── T2.3b 业务域 L2 profile 分档(连真 PG + 真 dict_biz_domains + fake LLM)──────────
def test_biz_l2_pint_candidate_gates_to_review(env, monkeypatch):
    # 内规 P-INT:LLM 业务域候选恒入 META_REVIEW —— 即便 auto_confirm 开也不放行(权威担责)。
    ctx, bids = env
    ctx = _ctx_l2(ctx, auto_confirm=True)
    biz0 = ctx.db.get_biz_domains()[0].name
    monkeypatch.setattr(s4, "make_llm_client", lambda *a, **k: _FakeBizClient([biz0]))
    dvid = _seed(
        ctx, bids, doc_number="京证监〔2024〕5号", issue_date=date(2024, 1, 1),
        title="某办法", corpus="P-INT",
    )
    res = s4.run(ctx, dvid)
    assert res.next_state is PS.META_REVIEW
    assert "业务域" in res.queue.reason
    assert res.evidence["biz_l2"] == {"needs_review": True, "biz_domains": [biz0], "source": "llm"}
    dv = ctx.db.get(DocVersion, dvid)
    assert dv.biz_domains == [biz0] and dv.biz_domain_source == "llm"


def test_biz_l2_pext_direct_lands(env, monkeypatch):
    # 外规 P-EXT:LLM 业务域直落 effective(sampling_rate=0)→ 仍自动放行 EMBEDDING,但已写权威字段。
    ctx, bids = env
    ctx = _ctx_l2(ctx, auto_confirm=True)
    biz0 = ctx.db.get_biz_domains()[0].name
    monkeypatch.setattr(s4, "make_llm_client", lambda *a, **k: _FakeBizClient([biz0]))
    dvid = _seed(
        ctx, bids, doc_number="京证监〔2024〕5号", issue_date=date(2024, 1, 1),
        title="某办法", corpus="P-EXT",
    )
    res = s4.run(ctx, dvid)
    assert res.next_state is PS.EMBEDDING  # 直落
    dv = ctx.db.get(DocVersion, dvid)
    assert dv.biz_domains == [biz0] and dv.biz_domain_source == "llm"


def test_biz_l2_manifest_conflict_prefers_manifest_and_gates(env, monkeypatch):
    # manifest 已给业务域 → 优先(source=manifest);与 LLM 不一致 → 冲突 → META_REVIEW(§7.1)。
    ctx, bids = env
    ctx = _ctx_l2(ctx, auto_confirm=True)
    names = [d.name for d in ctx.db.get_biz_domains()]
    manifest_biz, llm_biz = names[0], names[1]  # 两个不同字典值 → 冲突
    monkeypatch.setattr(s4, "make_llm_client", lambda *a, **k: _FakeBizClient([llm_biz]))
    dvid = _seed(
        ctx, bids, doc_number="京证监〔2024〕5号", issue_date=date(2024, 1, 1),
        title="某办法", corpus="P-EXT", biz_domain=manifest_biz,
    )
    res = s4.run(ctx, dvid)
    assert res.next_state is PS.META_REVIEW
    dv = ctx.db.get(DocVersion, dvid)
    assert dv.biz_domains == [manifest_biz] and dv.biz_domain_source == "manifest"  # manifest 优先
