"""B7 CLI 集成测试(typer CliRunner + 真 PG;不可达 skip)。

仅覆盖不写对象库的命令(queue list/show、status、queue degrade/reject + 编排装配)。
ingest 全链路 + queue fix 重入是 checkpoint B 的手动门([需 demo up]),不在此自动化。
"""

import pytest
from sqlalchemy import delete, select, text
from typer.testing import CliRunner
from ulid import ULID

from pipeline.cli import _build_stages, _structuring, app
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
from pipeline.stages import s1_parse, s2_qc
from pipeline.states import PipelineState as PS

runner = CliRunner()


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


def _seed_qc_failed(pg, bids, *, filename="跳号.docx") -> tuple[str, str]:
    """造 1 个 QC_FAILED 的 doc + 1 条 qc_fix 队列行(带条号缺口 evidence),返回 (dvid, qid)。"""
    bid, lid, dvid, qid = "cli_" + str(ULID()), str(ULID()), str(ULID()), str(ULID())
    bids.append(bid)
    evidence = {
        "failed": [
            {"index": 2, "name": "条号连续性", "value": 1.0, "threshold": 0.0,
             "evidence": {"missing": [3], "hint": "第2条后缺第3条(第1页)"}}
        ],
        "marginal": [],
    }
    with pg.session() as s:
        s.add(ImportBatch(batch_id=bid, source_dir="x"))
        s.add(Document(logical_id=lid, corpus_type="P-INT"))
        s.flush()
        s.add(
            DocVersion(
                doc_version_id=dvid, logical_id=lid, batch_id=bid, source_format="docx",
                source_hash="h" + dvid[:8], raw_object_key="k", source_filename=filename,
                pipeline_status=PS.QC_FAILED.value,
            )
        )
        s.flush()
        s.add(
            ReviewQueue(
                queue_id=qid, queue_type="qc_fix", doc_version_id=dvid,
                reason="质检未通过", evidence=evidence, status="open",
            )
        )
    return dvid, qid


def test_build_stages_wiring():
    # 编排装配根:REGISTERED→s1.start、PARSING→s1.run、QC_PENDING→s2.run、STRUCTURING→s3+s4 复合
    st = _build_stages()
    assert st[PS.REGISTERED] is s1_parse.start
    assert st[PS.PARSING] is s1_parse.run
    assert st[PS.QC_PENDING] is s2_qc.run
    assert st[PS.STRUCTURING] is _structuring


def test_queue_list_shows_open(sandbox):
    pg, bids = sandbox
    _, qid = _seed_qc_failed(pg, bids)
    r = runner.invoke(app, ["queue", "list"])
    assert r.exit_code == 0
    assert qid in r.output and "qc_fix" in r.output


def test_queue_show_prints_evidence_and_ir_path(sandbox):
    pg, bids = sandbox
    dvid, qid = _seed_qc_failed(pg, bids)
    r = runner.invoke(app, ["queue", "show", qid])
    assert r.exit_code == 0
    assert "条号连续性" in r.output
    assert "第2条后缺第3条(第1页)" in r.output  # 定位提示(条号 + 页码)
    assert f"ir/{dvid}.json" in r.output  # IR 片段路径


def test_queue_show_missing_id_exits_1(sandbox):
    pg, _ = sandbox
    r = runner.invoke(app, ["queue", "show", "no_such_id"])
    assert r.exit_code == 1


def test_status_lists_doc(sandbox):
    pg, bids = sandbox
    dvid, _ = _seed_qc_failed(pg, bids)
    r = runner.invoke(app, ["status"])
    assert r.exit_code == 0
    assert dvid in r.output and "QC_FAILED" in r.output


def test_queue_degrade_via_cli(sandbox):
    # degrade 现在重入 STRUCTURING + 置 degraded(走索引终于 DEGRADED_INDEXED);seeded 件无 IR,
    # 韧性推进在 s3 处中止(不崩命令),doc 停 STRUCTURING、degraded 已置位。
    pg, bids = sandbox
    dvid, qid = _seed_qc_failed(pg, bids)
    r = runner.invoke(app, ["queue", "degrade", qid])
    assert r.exit_code == 0
    assert "STRUCTURING" in r.output
    dv = pg.get(DocVersion, dvid)
    assert dv.degraded is True
    assert pg.get(ReviewQueue, qid).status == "closed"


def test_queue_reject_via_cli(sandbox):
    pg, bids = sandbox
    dvid, qid = _seed_qc_failed(pg, bids)
    r = runner.invoke(app, ["queue", "reject", qid])
    assert r.exit_code == 0
    assert pg.get(DocVersion, dvid).pipeline_status == "REJECTED"


def test_queue_degrade_missing_id_exits_1(sandbox):
    pg, _ = sandbox
    r = runner.invoke(app, ["queue", "degrade", "no_such_id"])
    assert r.exit_code == 1
