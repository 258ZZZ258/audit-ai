"""D4 report 测试。

- test_build_report_metrics:**免模型/免 Milvus**(ctx.milvus=None)——seed 多件不同状态历史 + chunks,
  验四项指标数学 + **无 t2_pass_rate/t4_pass_rate 键**。
- test_report_cli_persists:**Milvus-guarded 免模型**——CliRunner `report <batch>`,验输出 +
  retrieval_mode 探测 + 快照落库 import_batches.report。
"""

import pytest
from sqlalchemy import delete, text
from typer.testing import CliRunner
from ulid import ULID

from pipeline import cli
from pipeline.config import load_config
from pipeline.index.milvus_io import MilvusIO
from pipeline.index.pg_io import PgIO
from pipeline.index.pg_models import (
    Chunk,
    Document,
    DocVersion,
    ImportBatch,
    PipelineEvent,
)
from pipeline.stage_base import StageContext
from pipeline.verify.report import build_report

runner = CliRunner()


@pytest.fixture
def pg():
    io = PgIO.from_config(load_config())
    try:
        with io.session() as s:
            s.execute(text("select 1"))
    except Exception:
        pytest.skip("PG 不可达")
    return io


@pytest.fixture
def batch(pg):
    bid, lid = "rep_" + str(ULID()), str(ULID())
    created: list[str] = []

    def _doc(status: str, *, to_states: list[str], pages: list[int | None]) -> str:
        dvid = str(ULID())
        created.append(dvid)
        with pg.session() as s:
            s.get(ImportBatch, bid) or s.add(ImportBatch(batch_id=bid, source_dir="x"))
            if not s.get(Document, lid):
                s.add(Document(logical_id=lid, corpus_type="P-INT"))
            s.flush()
            s.add(
                DocVersion(
                    doc_version_id=dvid, logical_id=lid, batch_id=bid, source_format="docx",
                    source_hash="h" + dvid[:10], raw_object_key="k", pipeline_status=status,
                )
            )
            s.flush()
            prev = None
            for ts in to_states:  # 状态历史(供解析/QC 一次通过判定)
                s.add(PipelineEvent(doc_version_id=dvid, from_state=prev, to_state=ts))
                prev = ts
            for i, pg_no in enumerate(pages):
                s.add(
                    Chunk(
                        chunk_id=(f"{i}" + dvid)[:24], doc_version_id=dvid, text="x",
                        clause_path="1", clause_path_norm="1", seq=i, page_start=pg_no,
                        is_parent=False, is_table=False, chunk_status="effective",
                    )
                )
        return dvid

    yield pg, bid, _doc
    with pg.session() as s:
        s.execute(delete(Chunk).where(Chunk.doc_version_id.in_(created or [""])))
        s.execute(delete(PipelineEvent).where(PipelineEvent.doc_version_id.in_(created or [""])))
        s.execute(delete(DocVersion).where(DocVersion.doc_version_id.in_(created or [""])))
        s.execute(delete(Document).where(Document.logical_id == lid))
        s.execute(delete(ImportBatch).where(ImportBatch.batch_id == bid))


def test_build_report_metrics(batch):
    pg, bid, doc = batch
    # A 一次过(PARSING→QC_PENDING→STRUCTURING),chunk 页码 [1, None]
    doc("INDEXED", to_states=["PARSING", "QC_PENDING", "STRUCTURING"], pages=[1, None])
    # B 二次过(中途 QC_FAILED → 非一次通过)
    doc("INDEXED", to_states=["PARSING", "QC_PENDING", "QC_FAILED", "QC_PENDING", "STRUCTURING"],
        pages=[2])
    # C 解析失败(进 PARSING 未到 QC)
    doc("PARSE_FAILED", to_states=["PARSING", "PARSE_FAILED"], pages=[])
    # D S0 隔离(未进解析)
    doc("QUARANTINED", to_states=["QUARANTINED"], pages=[])

    ctx = StageContext(config=load_config(), db=pg, milvus=None)
    rep = build_report(ctx, bid)

    assert rep["doc_count"] == 4
    # 到 QC(A,B)=2 / 进 PARSING(A,B,C)=3
    assert rep["parse_success_rate"] == pytest.approx(2 / 3, abs=1e-4)
    assert rep["qc_first_pass_rate"] == 0.5  # 一次过(A)=1 / 到 QC(A,B)=2
    # 有页码(1,2)=2 / 总块(1,None,2)=3
    assert rep["anchor_fill_rate"] == pytest.approx(2 / 3, abs=1e-4)
    assert rep["status_counts"] == {"INDEXED": 2, "PARSE_FAILED": 1, "QUARANTINED": 1}
    assert rep["retrieval_mode"] is None  # milvus=None
    # M2:t2/t4 键已加;无 verify 留痕 → None(键有值或 None,不缺键)
    assert rep["t2_pass_rate"] is None and rep["t4_pass_rate"] is None


def test_report_aggregates_verify_events(batch):
    pg, bid, doc = batch
    a = doc("INDEXED", to_states=["PARSING", "QC_PENDING", "STRUCTURING"], pages=[1])
    b = doc("INDEXED", to_states=["PARSING", "QC_PENDING", "STRUCTURING"], pages=[1])
    # finalize 留痕:a 命中、b 未命中;两者 T4 均通过
    with pg.session() as s:
        for dvid, hit in ((a, True), (b, False)):
            s.add(PipelineEvent(
                doc_version_id=dvid, from_state="INDEXED", to_state="INDEXED", actor="finalize",
                detail={"verify": {"t2_hit": hit, "t4_pass": True, "t4_rate": 1.0}},
            ))
    rep = build_report(StageContext(config=load_config(), db=pg, milvus=None), bid)
    assert rep["t2_pass_rate"] == 0.5  # a 命中 / (a,b)
    assert rep["t4_pass_rate"] == 1.0  # 两者 T4 通过


def test_report_cli_persists(batch):
    from pymilvus import utility

    mio = MilvusIO(load_config())
    try:
        mio.connect()
        utility.list_collections()
    except Exception:
        pytest.skip("Milvus 不可达")
    mio.create_collection()

    pg, bid, doc = batch
    doc("INDEXED", to_states=["PARSING", "QC_PENDING", "STRUCTURING"], pages=[1])

    r = runner.invoke(cli.app, ["report", bid])
    assert r.exit_code == 0, r.output
    assert "解析成功率" in r.output and "retrieval_mode" in r.output
    assert "T2 冒烟" in r.output and "t2_pass_rate" in r.output  # M2:T2/T4 键已接入
    snap = pg.get(ImportBatch, bid).report  # 快照落库
    assert snap is not None and snap["batch_id"] == bid
    assert snap["retrieval_mode"] in ("hybrid", "dense_only")
