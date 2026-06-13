"""orchestrator 集成测试(连真 PG;不可达自动 skip)。用 fake stage 驱动状态机。"""

import pytest
from sqlalchemy import delete, select, text
from ulid import ULID

from pipeline.config import load_config
from pipeline.index.pg_io import PgIO
from pipeline.index.pg_models import (
    Document,
    DocVersion,
    ImportBatch,
    PipelineEvent,
    ReviewQueue,
)
from pipeline.orchestrator import Orchestrator
from pipeline.stage_base import QueueItem, QueueType, StageContext, StageResult
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
def doc_version(pg):
    bid, lid, dvid = "test_" + str(ULID())[:10], str(ULID()), str(ULID())
    pg.add(ImportBatch(batch_id=bid, source_dir="x"))
    pg.add(Document(logical_id=lid, corpus_type="P-INT"))
    pg.add(
        DocVersion(
            doc_version_id=dvid,
            logical_id=lid,
            batch_id=bid,
            source_format="docx",
            source_hash="h",
            raw_object_key="k",
            pipeline_status=PS.REGISTERED.value,
        )
    )
    yield dvid
    with pg.session() as s:
        s.execute(delete(ReviewQueue).where(ReviewQueue.doc_version_id == dvid))
        s.execute(delete(PipelineEvent).where(PipelineEvent.doc_version_id == dvid))
        s.execute(delete(DocVersion).where(DocVersion.doc_version_id == dvid))
        s.execute(delete(Document).where(Document.logical_id == lid))
        s.execute(delete(ImportBatch).where(ImportBatch.batch_id == bid))


def _ctx():
    return StageContext(config=load_config())


def _stage(next_state, *, queue=False):
    def stage(ctx, dvid):
        qi = QueueItem(QueueType.QC_FIX, dvid, "条号缺口", {"indicator": 2}) if queue else None
        return StageResult(next_state=next_state, queue=qi)

    return stage


def test_advances_until_human_wait_and_enqueues(pg, doc_version):
    # REGISTERED → PARSING → QC_PENDING → QC_FAILED(人工等待态,停)
    stages = {
        PS.REGISTERED: _stage(PS.PARSING),
        PS.PARSING: _stage(PS.QC_PENDING),
        PS.QC_PENDING: _stage(PS.QC_FAILED, queue=True),
    }
    steps = Orchestrator(pg, _ctx(), stages).run_until_idle()
    assert steps == 3
    assert pg.get(DocVersion, doc_version).pipeline_status == PS.QC_FAILED.value
    # 三次迁移各写一条 event
    with pg.session() as s:
        ev_q = select(PipelineEvent).where(PipelineEvent.doc_version_id == doc_version)
        evs = list(s.scalars(ev_q))
        qs = list(s.scalars(select(ReviewQueue).where(ReviewQueue.doc_version_id == doc_version)))
    hops = {(e.from_state, e.to_state) for e in evs}
    assert ("REGISTERED", "PARSING") in hops
    assert ("PARSING", "QC_PENDING") in hops
    assert ("QC_PENDING", "QC_FAILED") in hops
    # QC 失败入队 qc_fix
    assert len(qs) == 1 and qs[0].queue_type == "qc_fix" and qs[0].status == "open"


def test_human_wait_state_not_polled(pg, doc_version):
    # 文档先到 META_REVIEW(人工等待态),即便注册了 stage 也不应被轮询推进
    pg.transition(doc_version, PS.PARSING)
    pg.transition(doc_version, PS.QC_PENDING)
    pg.transition(doc_version, PS.STRUCTURING)
    pg.transition(doc_version, PS.META_REVIEW)
    stages = {PS.META_REVIEW: _stage(PS.EMBEDDING)}  # 即使映射了 META_REVIEW
    steps = Orchestrator(pg, _ctx(), stages).run_until_idle()
    assert steps == 0  # META_REVIEW ∉ WORKER_ADVANCEABLE,不轮询
    assert pg.get(DocVersion, doc_version).pipeline_status == PS.META_REVIEW.value


def test_no_registered_stage_stops(pg, doc_version):
    # REGISTERED 有 stage 推到 QC_PENDING,但 QC_PENDING 无 stage → 停在 QC_PENDING
    stages = {PS.REGISTERED: _stage(PS.PARSING), PS.PARSING: _stage(PS.QC_PENDING)}
    Orchestrator(pg, _ctx(), stages).run_until_idle()
    assert pg.get(DocVersion, doc_version).pipeline_status == PS.QC_PENDING.value
