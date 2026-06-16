"""s4_meta 集成测试(连真 PG + tmp ObjectStore;PG 不可达 skip)。"""

from datetime import date

import pytest
from sqlalchemy import delete, select, text
from ulid import ULID

from pipeline.config import load_config
from pipeline.index.object_store import ObjectStore
from pipeline.index.pg_io import PgIO
from pipeline.index.pg_models import Document, DocVersion, ImportBatch, PipelineEvent, ReviewQueue
from pipeline.ir import Block, BlockType, IRDocument, SourceFormat
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
            s.execute(delete(DocVersion).where(DocVersion.doc_version_id.in_(dvids)))
        if lids:
            s.execute(delete(Document).where(Document.logical_id.in_(lids)))
        if bids:
            s.execute(delete(ImportBatch).where(ImportBatch.batch_id.in_(bids)))


def _seed(ctx, bids, *, doc_number, issue_date, title, supersedes=None) -> str:
    """落 doc(STRUCTURING,带 manifest 字段)+ put_ir(版头含 京证监〔2024〕5号 / 2024年1月1日)。

    ``supersedes``:置 supersedes_version_id(模拟修订件;B-严 据此把修订件挡回 META_REVIEW)。
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
    ctx.db.add(Document(logical_id=lid, corpus_type="P-INT"))
    ctx.db.add(
        DocVersion(
            doc_version_id=dvid, logical_id=lid, batch_id=bid, source_format="docx",
            source_hash="h" + dvid[:8], raw_object_key="k", pipeline_status=PS.STRUCTURING.value,
            doc_number=doc_number, issue_date=issue_date, title=title,
            supersedes_version_id=supersedes,
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
