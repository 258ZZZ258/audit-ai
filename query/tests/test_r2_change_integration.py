"""T3/T4(集成):R2 端到端连真栈——182→226 双版本 + 手插 revision_note。

gate:PIPELINE_EMBEDDING_MODEL + PG + Milvus + fixtures(build_fixtures.py)。未满足即 skip。
复用 version_demo 的真实修订对(226 manifest 声明 supersedes 182,s0 解析)。
"""

from __future__ import annotations

import os
from pathlib import Path

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
    RevisionNote,
)
from pipeline.config import load_config
from pipeline.index.embedding_client import EmbeddingClient
from pipeline.index.milvus_io import MilvusIO
from pipeline.index.object_store import ObjectStore
from pipeline.index.pg_io import PgIO
from pipeline.stage_base import StageContext
from query.change.r2_change import answer_change
from query.config import load_query_config
from query.contract import RouteType
from query.graph import QueryAgent
from query.retrieve.hybrid import Retriever

FIX = Path(__file__).resolve().parents[2] / "fixtures"
OLD_PDF, NEW_PDF = "ext_xxpl_182.pdf", "ext_xxpl_226.pdf"
CHANGE_QUERY = "信息披露管理办法最近修订改了哪些内容"
REVISION_TEXT = "为对接2023年信息披露新规,修订相关披露义务条款。"


@pytest.fixture(scope="module")
def stack():
    if not os.environ.get("PIPELINE_EMBEDDING_MODEL"):
        pytest.skip("未设 PIPELINE_EMBEDDING_MODEL;R2 集成跳过")
    _pairs = [("batch01", OLD_PDF), ("batch02_revision", NEW_PDF)]
    if not all((FIX / b / f).exists() for b, f in _pairs):
        pytest.skip("fixtures 未构建")
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


def _clean(pg, mio, dvids):
    for dvid in dvids:
        try:
            mio.delete(dvid)
        except Exception:
            pass
    try:
        mio.flush()
    except Exception:
        pass
    with pg.session() as s:
        for dvid in dvids:
            child = select(Chunk.chunk_id).where(Chunk.doc_version_id == dvid)
            s.execute(delete(ClauseTag).where(ClauseTag.chunk_id.in_(child)))
            s.execute(delete(RevisionNote).where(RevisionNote.doc_version_id == dvid))
            s.execute(delete(Chunk).where(Chunk.doc_version_id == dvid))
            s.execute(delete(PipelineEvent).where(PipelineEvent.doc_version_id == dvid))
            s.execute(delete(RemediationRecord).where(RemediationRecord.doc_version_id == dvid))
            s.execute(delete(ReviewQueue).where(ReviewQueue.doc_version_id == dvid))
        lids = list(
            s.scalars(select(DocVersion.logical_id).where(DocVersion.doc_version_id.in_(dvids)))
        )
        bids = list(
            s.scalars(select(DocVersion.batch_id).where(DocVersion.doc_version_id.in_(dvids)))
        )
        s.execute(delete(DocVersion).where(DocVersion.doc_version_id.in_(dvids)))
        if lids:
            s.execute(delete(Document).where(Document.logical_id.in_(lids)))
        if bids:
            s.execute(delete(ImportBatch).where(ImportBatch.batch_id.in_(bids)))


def test_r2_change_end_to_end(stack, tmp_path, mini_batch, ingest_index):
    pg, mio, ctx = stack
    d1, m1 = mini_batch(tmp_path, "batch01", OLD_PDF)
    _, old_dvids = ingest_index(pg, ctx, d1, m1)
    d2, m2 = mini_batch(tmp_path, "batch02_revision", NEW_PDF)
    _, new_dvids = ingest_index(pg, ctx, d2, m2)
    (old_dvid,), (new_dvid,) = old_dvids, new_dvids
    pg.add(RevisionNote(doc_version_id=new_dvid, raw_text=REVISION_TEXT))

    try:
        # 226 supersedes 182 → 现行 226、前驱 182
        assert pg.get(DocVersion, new_dvid).supersedes_version_id == old_dvid

        res = answer_change(CHANGE_QUERY, Retriever(ctx.embedding, mio, load_query_config()), pg)
        assert res.route_type is RouteType.CHANGE
        full = " ".join(b.content for b in res.answer_blocks)
        assert new_dvid in full and old_dvid in full       # 版本对
        assert "条款变更" in full                            # diff 段
        assert REVISION_TEXT in full                         # 修订原因回查(非推测)
        # 变更条款带四级引用(SC5,R2-CITATION-ASSERTION):非空 + 关键锚点字段
        assert res.citations, "变更条款应带四级引用"
        assert all(c.clause_id for c in res.citations)
        c0 = res.citations[0]
        assert c0.clause_path                       # 条款路径
        assert c0.doc_title or c0.doc_no            # 文档级(标题/文号至少其一)
        assert c0.status == "effective"             # 状态:现行版本
        assert c0.page_start is not None            # 页码锚点

        # graph 端到端:变更问句 → route_type=change
        agent = QueryAgent(
            Retriever(ctx.embedding, mio, load_query_config()), pg, None, load_query_config()
        )
        assert agent.ask(CHANGE_QUERY).route_type is RouteType.CHANGE
    finally:
        _clean(pg, mio, [old_dvid, new_dvid])
