"""P2 回归:finalize 的 T2/T4 评测异常须**据实留痕为失败**(t4_pass=False + error),不被吞掉
——否则 report 聚合不到该 doc,通过率显 None 掩盖失败(V0.1 §21.2:不阻断终态,但写入报告)。

连 PG(留痕事件写入 + DocVersion 锚点);monkeypatch run_replay/run_smoke 触发异常,**免栈免模型**。
"""

from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select, text
from ulid import ULID

from common.pg_models import Document, DocVersion, ImportBatch, PipelineEvent
from pipeline.config import load_config
from pipeline.index.object_store import ObjectStore
from pipeline.index.pg_io import PgIO
from pipeline.stage_base import StageContext
from pipeline.stages import finalize


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
def indexed_doc(pg_ctx):
    """一个 INDEXED 件(仅元数据,留痕事件需 DocVersion 锚点;评测被 monkeypatch,不需 chunk/向量)。"""
    pg, ctx = pg_ctx
    bid, lid, dvid = "fv_" + str(ULID()), str(ULID()), str(ULID())
    with pg.session() as s:
        s.add(ImportBatch(batch_id=bid, source_dir="x"))
        s.add(Document(logical_id=lid, corpus_type="P-INT"))
        s.flush()
        s.add(
            DocVersion(
                doc_version_id=dvid, logical_id=lid, batch_id=bid, source_format="docx",
                source_hash="h" + dvid[:8], raw_object_key="k", pipeline_status="INDEXED",
                perm_tag="内部", biz_domain="X", issuer="CSRC",
            )
        )
    yield pg, ctx, dvid
    with pg.session() as s:
        s.execute(delete(PipelineEvent).where(PipelineEvent.doc_version_id == dvid))
        s.execute(delete(DocVersion).where(DocVersion.doc_version_id == dvid))
        s.execute(delete(Document).where(Document.logical_id == lid))
        s.execute(delete(ImportBatch).where(ImportBatch.batch_id == bid))


def _latest_verify(pg, dvid):
    """该 doc 最新一条 pipeline_events.detail['verify'](无则 None)。"""
    with pg.session() as s:
        evs = list(
            s.scalars(
                select(PipelineEvent)
                .where(PipelineEvent.doc_version_id == dvid)
                .order_by(PipelineEvent.id)
            )
        )
    vs = [e.detail["verify"] for e in evs if (e.detail or {}).get("verify")]
    return vs[-1] if vs else None


def test_finalize_records_t4_failure(indexed_doc, monkeypatch):
    """T4(run_replay)抛异常(源文件/渲染件缺失等)→ 留痕 t4_pass=False + error,而非整条消失。"""
    pg, ctx, dvid = indexed_doc

    def _boom(*a, **k):
        raise FileNotFoundError("rendition missing")

    monkeypatch.setattr("eval.anchor_replay.run_replay", _boom)
    finalize._run_verify(ctx, dvid)  # 不应抛(异常被吞为失败留痕)

    v = _latest_verify(pg, dvid)
    assert v is not None  # 失败也必写事件(旧实现:只 warning,不写 → report 显 None)
    assert v["t4_pass"] is False  # 计为失败 → report 据实拉低通过率,而非 None
    assert v["t2_hit"] is None
    assert "error" in v and "rendition missing" in v["error"]


def test_finalize_preserves_t4_when_t2_errors(indexed_doc, monkeypatch):
    """仅 T2(run_smoke)抛异常时,已得的 T4 结果不丢:t4_pass 保留、t2_hit=None + error。"""
    pg, ctx, dvid = indexed_doc
    # 让 smoke 分支进入(embedding+milvus 非 None;run_smoke 被 monkeypatch,不真调)
    ctx = StageContext(
        config=ctx.config, object_store=ctx.object_store, db=ctx.db,
        embedding=object(), milvus=object(),
    )
    monkeypatch.setattr(
        "eval.anchor_replay.run_replay",
        lambda *a, **k: SimpleNamespace(passed=True, pass_rate=1.0),
    )

    def _boom(*a, **k):
        raise RuntimeError("milvus search failed")

    monkeypatch.setattr("eval.smoke.run_smoke", _boom)
    finalize._run_verify(ctx, dvid)

    v = _latest_verify(pg, dvid)
    assert v is not None
    assert v["t4_pass"] is True  # T4 已成功,不被 T2 的崩拖掉
    assert v["t2_hit"] is None
    assert "error" in v and "milvus search failed" in v["error"]
