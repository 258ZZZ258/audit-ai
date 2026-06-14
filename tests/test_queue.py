"""queue 处置流集成测试(连真 PG;不可达 skip)。临时造 doc + 队列行,测完按 FK 序清理。"""

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
    RemediationRecord,
    ReviewQueue,
)
from pipeline.queue import dispose
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
def sandbox(pg):
    bids: list[str] = []
    yield pg, bids
    with pg.session() as s:
        dvs = list(s.scalars(select(DocVersion).where(DocVersion.batch_id.in_(bids or [""]))))
        dvids = [d.doc_version_id for d in dvs]
        lids = {d.logical_id for d in dvs}
        if dvids:
            s.execute(delete(RemediationRecord).where(RemediationRecord.doc_version_id.in_(dvids)))
            s.execute(delete(ReviewQueue).where(ReviewQueue.doc_version_id.in_(dvids)))
            s.execute(delete(PipelineEvent).where(PipelineEvent.doc_version_id.in_(dvids)))
            s.execute(delete(DocVersion).where(DocVersion.doc_version_id.in_(dvids)))
        if lids:
            s.execute(delete(Document).where(Document.logical_id.in_(lids)))
        if bids:
            s.execute(delete(ImportBatch).where(ImportBatch.batch_id.in_(bids)))


def _seed(pg, bids, state: PS, queue_type: str) -> tuple[str, str]:
    """造 1 个处于 ``state`` 的 doc + 1 条 open 的 ``queue_type`` 队列行,返回 (dvid, qid)。"""
    bid, lid, dvid, qid = "q_" + str(ULID()), str(ULID()), str(ULID()), str(ULID())
    bids.append(bid)
    with pg.session() as s:
        s.add(ImportBatch(batch_id=bid, source_dir="x"))
        s.add(Document(logical_id=lid, corpus_type="P-INT"))
        s.flush()  # 父表先落,满足 doc_versions FK
        s.add(
            DocVersion(
                doc_version_id=dvid, logical_id=lid, batch_id=bid, source_format="docx",
                source_hash="h" + dvid[:8], raw_object_key="k", pipeline_status=state.value,
            )
        )
        s.flush()  # doc_version 先落,满足 review_queue FK
        s.add(
            ReviewQueue(
                queue_id=qid, queue_type=queue_type, doc_version_id=dvid,
                reason="测试", evidence={"x": 1}, status="open",
            )
        )
    return dvid, qid


def _remediations(pg, qid: str) -> list[RemediationRecord]:
    with pg.session() as s:
        return list(s.scalars(select(RemediationRecord).where(RemediationRecord.queue_id == qid)))


def test_fix_reenters_qc(sandbox):
    pg, bids = sandbox
    dvid, qid = _seed(pg, bids, PS.QC_FAILED, "qc_fix")
    out = dispose(pg, qid, "fix", operator="alice", reason="补了条号")
    assert (out.before_state, out.after_state) == ("QC_FAILED", "QC_PENDING")
    assert pg.get(DocVersion, dvid).pipeline_status == "QC_PENDING"  # 重入质检
    q = pg.get(ReviewQueue, qid)
    assert q.status == "closed" and q.disposition == "fix" and q.operator == "alice"
    assert q.processed_at is not None
    rr = _remediations(pg, qid)
    assert len(rr) == 1
    assert (rr[0].before_state, rr[0].after_state) == ("QC_FAILED", "QC_PENDING")
    assert rr[0].operator == "alice" and rr[0].reason == "补了条号"


def test_degrade_to_terminal(sandbox):
    pg, bids = sandbox
    dvid, qid = _seed(pg, bids, PS.QC_FAILED, "qc_fix")
    out = dispose(pg, qid, "degrade", operator="bob")
    assert out.after_state == "DEGRADED_INDEXED"
    assert pg.get(DocVersion, dvid).pipeline_status == "DEGRADED_INDEXED"


def test_reject_to_terminal(sandbox):
    pg, bids = sandbox
    dvid, qid = _seed(pg, bids, PS.QC_FAILED, "qc_fix")
    dispose(pg, qid, "reject", operator="bob")
    assert pg.get(DocVersion, dvid).pipeline_status == "REJECTED"


def test_release_reenters_parsing(sandbox):
    pg, bids = sandbox
    dvid, qid = _seed(pg, bids, PS.QUARANTINED, "quarantine")
    dispose(pg, qid, "release", operator="bob")
    assert pg.get(DocVersion, dvid).pipeline_status == "PARSING"  # 隔离裁决后重入解析


def test_approve_meta_to_embedding(sandbox):
    pg, bids = sandbox
    dvid, qid = _seed(pg, bids, PS.META_REVIEW, "meta_confirm")
    dispose(pg, qid, "approve", operator="bob")
    assert pg.get(DocVersion, dvid).pipeline_status == "EMBEDDING"


def test_cross_type_disposition_rejected(sandbox):
    # 对 qc_fix 件用 approve(meta_confirm 专属)→ 拒绝,状态/队列均不动
    pg, bids = sandbox
    dvid, qid = _seed(pg, bids, PS.QC_FAILED, "qc_fix")
    with pytest.raises(ValueError):
        dispose(pg, qid, "approve", operator="bob")
    assert pg.get(DocVersion, dvid).pipeline_status == "QC_FAILED"
    assert pg.get(ReviewQueue, qid).status == "open"
    assert _remediations(pg, qid) == []


def test_illegal_state_rolls_back_atomically(sandbox):
    # degrade 仅 QC_FAILED 合法;对 PARSE_FAILED 件 degrade → can_transition 拒 → 整事务回滚
    pg, bids = sandbox
    dvid, qid = _seed(pg, bids, PS.PARSE_FAILED, "qc_fix")
    with pytest.raises(ValueError):
        dispose(pg, qid, "degrade", operator="bob")
    assert pg.get(DocVersion, dvid).pipeline_status == "PARSE_FAILED"  # 未动
    assert pg.get(ReviewQueue, qid).status == "open"  # 未关
    assert _remediations(pg, qid) == []  # remediation 一并回滚


def test_already_closed_rejected(sandbox):
    pg, bids = sandbox
    dvid, qid = _seed(pg, bids, PS.QC_FAILED, "qc_fix")
    dispose(pg, qid, "fix", operator="alice")
    with pytest.raises(ValueError):  # 已关,二次处置拒绝(只产生一条 remediation)
        dispose(pg, qid, "fix", operator="alice")
    assert len(_remediations(pg, qid)) == 1
