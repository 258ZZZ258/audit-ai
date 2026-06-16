"""B7 CLI 集成测试(typer CliRunner + 真 PG;不可达 skip)。

仅覆盖不写对象库的命令(queue list/show、status、queue degrade/reject + 编排装配)。
ingest 全链路 + queue fix 重入是 checkpoint B 的手动门([需 demo up]),不在此自动化。
"""

import pytest
from sqlalchemy import delete, select, text
from typer.testing import CliRunner
from ulid import ULID

from pipeline import cli
from pipeline.cli import _build_stages, _obligation_chunk_ids, _print_hit, _structuring, app
from pipeline.config import load_config
from pipeline.index.pg_io import PgIO
from pipeline.index.pg_models import (
    Chunk,
    ClauseTag,
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


def _force_mode_a(monkeypatch):
    """固定 A 模式(关自动放行):验 dispose 机制的测试与模式无关,A 模式用轻上下文、不依赖 Milvus/模型
    (B 模式下 degrade/release 会走 worker 上下文连 Milvus,使本该 PG-only 的测试耦合 Milvus)。"""
    base = load_config()
    a_cfg = base.model_copy(
        update={"toggles": base.toggles.model_copy(update={"auto_confirm_meta_no_conflict": False})}
    )
    monkeypatch.setattr(cli, "load_config", lambda *a, **k: a_cfg)


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


def test_print_hit_obligation_marker(capsys):
    """M3 #1:义务 hit 渲染带 [义务] 标,非义务不带(免栈渲染单测)。"""
    h = {"score": 0.5, "chunk_id": "c" * 24, "doc_version_id": "d" * 26,
         "clause_path": "第一条", "status": "effective", "page_start": 1}
    _print_hit(1, h, None, is_obligation=True)
    assert "[义务]" in capsys.readouterr().out
    _print_hit(1, h, None, is_obligation=False)
    assert "[义务]" not in capsys.readouterr().out


def test_obligation_chunk_ids(pg):
    """M3 #1:_obligation_chunk_ids 回 PG 查 is_obligation 标的 chunk(连 PG 免模型)。"""
    bid, lid, dvid = "cli_" + str(ULID()), str(ULID()), str(ULID())
    cids = [("o" + dvid)[:24], ("n" + dvid)[:24]]  # o 标义务,n 不标
    try:
        with pg.session() as s:
            s.add(ImportBatch(batch_id=bid, source_dir="x"))
            s.add(Document(logical_id=lid, corpus_type="P-INT"))
            s.flush()
            s.add(DocVersion(
                doc_version_id=dvid, logical_id=lid, batch_id=bid, source_format="docx",
                source_hash="h" + dvid[:8], raw_object_key="k", pipeline_status="INDEXED"))
            s.flush()
            for i, cid in enumerate(cids):
                s.add(Chunk(chunk_id=cid, doc_version_id=dvid, text="x", clause_path="1",
                            clause_path_norm="1", seq=i, page_start=1, is_parent=False,
                            is_table=False, chunk_status="effective"))
            s.flush()
            s.add(ClauseTag(
                chunk_id=cids[0], tag_type="is_obligation", tag_value="true", evidence="应当"))
        assert _obligation_chunk_ids(pg, cids) == {cids[0]}  # 只 o 标了义务
        assert _obligation_chunk_ids(pg, []) == set()
    finally:
        with pg.session() as s:
            s.execute(delete(ClauseTag).where(ClauseTag.chunk_id.in_(cids)))
            s.execute(delete(Chunk).where(Chunk.doc_version_id == dvid))
            s.execute(delete(DocVersion).where(DocVersion.doc_version_id == dvid))
            s.execute(delete(Document).where(Document.logical_id == lid))
            s.execute(delete(ImportBatch).where(ImportBatch.batch_id == bid))


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


def test_queue_degrade_via_cli(sandbox, monkeypatch):
    # degrade 重入 STRUCTURING + 置 degraded;seeded 件无 IR → s3 推进异常被**surfaced**:
    # 处置已落库(degraded/关单/迁移生效)但推进中止 → **非零退出**(契约:推进失败不静默 exit 0)。
    pg, bids = sandbox
    _force_mode_a(monkeypatch)  # 验 dispose 机制(与模式无关),固定 A 模式保持 PG-only
    dvid, qid = _seed_qc_failed(pg, bids)
    r = runner.invoke(app, ["queue", "degrade", qid])
    assert r.exit_code == 1  # s3 缺 IR 中止 → 推进失败,非零退出
    assert "STRUCTURING" in r.output and "推进失败" in r.output
    dv = pg.get(DocVersion, dvid)
    assert dv.degraded is True  # 处置副作用仍生效(落库在推进之前)
    assert pg.get(ReviewQueue, qid).status == "closed"


def test_queue_reject_via_cli(sandbox):
    pg, bids = sandbox
    dvid, qid = _seed_qc_failed(pg, bids)
    r = runner.invoke(app, ["queue", "reject", qid])
    assert r.exit_code == 0
    assert pg.get(DocVersion, dvid).pipeline_status == "REJECTED"


def test_queue_degrade_missing_id_exits_1(sandbox, monkeypatch):
    pg, _ = sandbox
    _force_mode_a(monkeypatch)  # 固定 A 模式:坏 id 在轻上下文即 KeyError,不必连 Milvus
    r = runner.invoke(app, ["queue", "degrade", "no_such_id"])
    assert r.exit_code == 1


def test_advance_one_guards_against_transient_strand(sandbox):
    # B1 回归:无 s5 stage(轻上下文)时,文档停在过渡态 EMBEDDING 必须**报错**,不静默成功——
    # 否则 dispose/ingest 在 B 模式会返成功却把文档搁浅 EMBEDDING、永不可检索。
    pg, bids = sandbox
    bid, lid, dvid = "cli_b1_" + str(ULID()), str(ULID()), str(ULID())
    bids.append(bid)
    with pg.session() as s:
        s.add(ImportBatch(batch_id=bid, source_dir="x"))
        s.add(Document(logical_id=lid, corpus_type="P-INT"))
        s.flush()
        s.add(DocVersion(
            doc_version_id=dvid, logical_id=lid, batch_id=bid, source_format="docx",
            source_hash="h" + dvid[:8], raw_object_key="k", pipeline_status=PS.EMBEDDING.value))
    _pg, ctx = cli._context()  # 轻上下文(无 embedding/milvus → 不注册 s5 stage)
    steps, final, error = cli._advance_one(pg, ctx, dvid)
    assert final == PS.EMBEDDING.value
    assert error is not None and "搁浅" in error


# ── C7 · meta(META_REVIEW 闸)/ search 参数校验 ───────────────────
def _seed_meta_review(pg, bids, *, conflicts: list[dict] | None = None) -> tuple[str, str, str]:
    """造 1 个 META_REVIEW 的 doc + 1 条 meta_confirm 队列行,返回 (batch_id, dvid, qid)。"""
    bid, lid, dvid, qid = "cli_" + str(ULID()), str(ULID()), str(ULID()), str(ULID())
    bids.append(bid)
    evidence = {"conflicts": conflicts or []}
    with pg.session() as s:
        s.add(ImportBatch(batch_id=bid, source_dir="x"))
        s.add(Document(logical_id=lid, corpus_type="P-INT", title="测试办法"))
        s.flush()
        s.add(
            DocVersion(
                doc_version_id=dvid, logical_id=lid, batch_id=bid, source_format="docx",
                source_hash="h" + dvid[:8], raw_object_key="k", title="测试办法",
                pipeline_status=PS.META_REVIEW.value,
            )
        )
        s.flush()
        s.add(
            ReviewQueue(
                queue_id=qid, queue_type="meta_confirm", doc_version_id=dvid,
                reason="元数据待人工确认" if not conflicts else "L1/manifest 元数据冲突",
                evidence=evidence, status="open",
            )
        )
    return bid, dvid, qid


def test_meta_list_shows_open_with_conflicts(sandbox):
    pg, bids = sandbox
    conflicts = [{"field": "doc_number", "manifest": "证监会令第182号", "extracted": "第180号"}]
    _, dvid, qid = _seed_meta_review(pg, bids, conflicts=conflicts)
    r = runner.invoke(app, ["meta", "list"])
    assert r.exit_code == 0
    assert qid in r.output and "⚠冲突×1" in r.output
    assert "doc_number" in r.output and "证监会令第182号" in r.output  # 冲突明细


def test_meta_list_marks_no_conflict(sandbox):
    pg, bids = sandbox
    _, _, qid = _seed_meta_review(pg, bids)  # conflicts=[]
    r = runner.invoke(app, ["meta", "list"])
    assert r.exit_code == 0
    assert qid in r.output and "无冲突" in r.output


def test_meta_confirm_requires_exactly_one_arg():
    # 既不给 queue_id 也不给 --batch → 退 1(参数校验先于触栈,无需 demo up)
    r = runner.invoke(app, ["meta", "confirm"])
    assert r.exit_code == 1
    # 同时给两者 → 互斥退 1
    r = runner.invoke(app, ["meta", "confirm", "some_id", "--batch", "b1"])
    assert r.exit_code == 1


def test_search_invalid_corpus_exits_1():
    # --corpus 仅 internal|external;非法值在触 embedding/milvus 前即退 1(无需 demo up)
    r = runner.invoke(app, ["search", "信息披露", "--corpus", "bogus"])
    assert r.exit_code == 1
    assert "internal|external" in r.output


# 注:M2 起 `verify smoke|replay|reconcile`、`rebuild` 已是真实组件(替换 D5 占位),
# 其行为由 test_smoke/test_anchor_replay/test_reconcile/test_rebuild(连真栈)覆盖。
