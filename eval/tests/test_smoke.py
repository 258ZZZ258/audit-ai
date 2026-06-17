"""A1 · T2 批次冒烟 smoke 测试。

gate:PIPELINE_EMBEDDING_MODEL + PG + Milvus + soffice。自造唯一内规 docx → ingest→confirm→INDEXED →
`run_smoke`:断言该件命中(hit@N)且 search 携带 status=effective 过滤位、pass_rate=1.0。
"""

import os

import pytest
from sqlalchemy import delete, select, text

from common.pg_models import (
    Chunk,
    ClauseTag,
    Document,
    DocVersion,
    ImportBatch,
    PipelineEvent,
    RemediationRecord,
    ReviewQueue,
)
from eval.report import build_report
from eval.smoke import run_smoke
from pipeline.config import load_config
from pipeline.index.embedding_client import EmbeddingClient
from pipeline.index.milvus_io import MilvusIO
from pipeline.index.object_store import ObjectStore
from pipeline.index.pg_io import PgIO
from pipeline.stage_base import StageContext


@pytest.fixture(scope="module")
def stack():
    if not os.environ.get("PIPELINE_EMBEDDING_MODEL"):
        pytest.skip("未设 PIPELINE_EMBEDDING_MODEL;T2 冒烟端到端跳过")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    cfg = load_config()
    pg = PgIO.from_config(cfg)
    try:
        with pg.session() as s:
            s.execute(text("select 1"))
    except Exception:
        pytest.skip("PG 不可达")
    mio = MilvusIO(cfg)
    try:
        mio.connect()
        mio.create_collection()
    except Exception:
        pytest.skip("Milvus 不可达")
    emb = EmbeddingClient.from_config(cfg)
    try:
        emb.embed(["探测"])
    except Exception as e:
        pytest.skip(f"BGE-M3 加载失败: {e}")
    ctx = StageContext(
        config=cfg, object_store=ObjectStore.from_config(cfg), db=pg, embedding=emb, milvus=mio
    )
    yield pg, mio, ctx
    mio.disconnect()


def test_smoke_hits_with_status_filter(stack, soffice, tmp_path, unique_docx, ingest_index):
    pg, mio, ctx = stack
    d, m = unique_docx(tmp_path)  # 唯一件避开 SHA 去重
    bid, dvids = ingest_index(pg, ctx, d, m)
    try:
        assert dvids
        (dvid,) = dvids
        assert pg.get(DocVersion, dvid).pipeline_status == "INDEXED"
        r = run_smoke(ctx, [dvid])
        rec = r.per_doc[0]
        assert rec["hit"], rec  # 合成查询(标题+首条款)命中本件
        assert rec["has_status_filter"]  # search 携带 status=effective 过滤位(E802 反例的反面)
        assert rec["error_code"] is None
        assert r.passed and r.pass_rate == 1.0
    finally:
        _cleanup(pg, mio, bid, dvids)


def _cleanup(pg, mio, bid, dvids):
    for d_ in dvids:
        mio.delete(d_)
    mio.flush()
    with pg.session() as s:
        for d_ in dvids:
            s.execute(delete(RemediationRecord).where(RemediationRecord.doc_version_id == d_))
            s.execute(delete(ReviewQueue).where(ReviewQueue.doc_version_id == d_))
            s.execute(  # E1 clause_tags 是 chunk 的 FK 子,先删
                delete(ClauseTag).where(
                    ClauseTag.chunk_id.in_(
                        select(Chunk.chunk_id).where(Chunk.doc_version_id == d_)
                    )
                )
            )
            s.execute(delete(Chunk).where(Chunk.doc_version_id == d_))
            s.execute(delete(PipelineEvent).where(PipelineEvent.doc_version_id == d_))
        lids = [
            x.logical_id
            for x in s.scalars(select(DocVersion).where(DocVersion.batch_id == bid))
        ]
        s.execute(delete(DocVersion).where(DocVersion.batch_id == bid))
        if lids:
            s.execute(delete(Document).where(Document.logical_id.in_(lids)))
        s.execute(delete(ImportBatch).where(ImportBatch.batch_id == bid))


def test_finalize_stores_verify_then_report_aggregates(stack, soffice, tmp_path,
                                                       unique_docx, ingest_index):
    # C2 + C1 端到端:ingest→INDEXED→finalize 跑 T2/T4 留痕(C2)→ report 聚合 t2/t4(C1)
    pg, mio, ctx = stack
    d, m = unique_docx(tmp_path)
    bid, dvids = ingest_index(pg, ctx, d, m)
    try:
        (dvid,) = dvids
        with pg.session() as s:
            verify_evs = [
                e for e in s.scalars(
                    select(PipelineEvent).where(PipelineEvent.doc_version_id == dvid))
                if (e.detail or {}).get("verify")
            ]
        assert verify_evs, "finalize 未留 verify 痕(C2)"
        v = verify_evs[-1].detail["verify"]
        assert v["t2_hit"] is True and v["t4_pass"] is True  # 该件 T2 命中 + T4 回放过
        rep = build_report(ctx, bid)  # C1:从留痕聚合
        assert rep["t2_pass_rate"] == 1.0 and rep["t4_pass_rate"] == 1.0
    finally:
        _cleanup(pg, mio, bid, dvids)
