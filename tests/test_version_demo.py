"""D2 batch02 联调 + 版本可见性(**V4** 端到端)。

gate:PIPELINE_EMBEDDING_MODEL(本地 BGE-M3)+ PG + Milvus + fixtures,缺任一则 skip。
用真实修订对(信息披露 182 → 226,226 manifest 声明 supersedes 182)走完整路径:
ingest 182 → meta confirm → INDEXED;ingest 226(s0 真实解析 supersedes)→ meta confirm → INDEXED →
`_advance_one` 自动 finalize 切换。断言:226 继承 182 logical + supersedes 解析对、182 置 superseded;
默认 search 不见旧版 182、`--include-superseded` 见 182(V4)。

为聚焦两件外规 PDF(且免 docx soffice 渲染),从 fixtures 各抽**单件**临时批(原 manifest 行不变)。
"""

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
)
from pipeline.config import load_config
from pipeline.index.embedding_client import EmbeddingClient
from pipeline.index.milvus_io import MilvusIO
from pipeline.index.object_store import ObjectStore
from pipeline.index.pg_io import PgIO
from pipeline.stage_base import StageContext

FIX = Path("fixtures")
OLD_PDF, NEW_PDF = "ext_xxpl_182.pdf", "ext_xxpl_226.pdf"


@pytest.fixture(scope="module")
def stack():
    if not os.environ.get("PIPELINE_EMBEDDING_MODEL"):
        pytest.skip("未设 PIPELINE_EMBEDDING_MODEL(本地 BGE-M3);D2 端到端跳过")
    pdfs = [FIX / "batch01" / OLD_PDF, FIX / "batch02_revision" / NEW_PDF]
    if not all(p.exists() for p in pdfs):
        pytest.skip("fixtures 未构建(build_fixtures.py --all)")
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


def _cleanup(pg, mio, batch_ids: list[str]) -> None:
    with pg.session() as s:
        dvs = list(s.scalars(select(DocVersion).where(DocVersion.batch_id.in_(batch_ids or [""]))))
    dvids = [d.doc_version_id for d in dvs]
    lids = {d.logical_id for d in dvs}
    for d in dvids:
        mio.delete(d)
    mio.flush()
    with pg.session() as s:
        if dvids:
            s.execute(delete(RemediationRecord).where(RemediationRecord.doc_version_id.in_(dvids)))
            s.execute(delete(ReviewQueue).where(ReviewQueue.doc_version_id.in_(dvids)))
            s.execute(  # E1 clause_tags 是 chunk 的 FK 子,先删
                delete(ClauseTag).where(
                    ClauseTag.chunk_id.in_(
                        select(Chunk.chunk_id).where(Chunk.doc_version_id.in_(dvids))
                    )
                )
            )
            s.execute(delete(Chunk).where(Chunk.doc_version_id.in_(dvids)))
            s.execute(delete(PipelineEvent).where(PipelineEvent.doc_version_id.in_(dvids)))
            s.execute(delete(DocVersion).where(DocVersion.doc_version_id.in_(dvids)))
        if lids:
            s.execute(delete(Document).where(Document.logical_id.in_(lids)))
        if batch_ids:
            s.execute(delete(ImportBatch).where(ImportBatch.batch_id.in_(batch_ids)))


def _dvids(res) -> list[str]:
    return [h["doc_version_id"] for h in res.hits]


def test_v4_revision_switch_and_visibility(stack, tmp_path, mini_batch, ingest_index):
    pg, mio, ctx = stack
    batches: list[str] = []
    try:
        # 1) 旧版 182 入库到 INDEXED(无 supersedes,finalize no-op)
        d1, m1 = mini_batch(tmp_path, "batch01", OLD_PDF)
        b1, old_dvids = ingest_index(pg, ctx, d1, m1)
        batches.append(b1)
        (old_dvid,) = old_dvids
        assert pg.get(DocVersion, old_dvid).pipeline_status == "INDEXED"

        # 2) 新版 226 入库(s0 真实解析 supersedes 182)→ INDEXED → 自动 finalize 切换
        d2, m2 = mini_batch(tmp_path, "batch02_revision", NEW_PDF)
        b2, new_dvids = ingest_index(pg, ctx, d2, m2)
        batches.append(b2)
        (new_dvid,) = new_dvids
        new = pg.get(DocVersion, new_dvid)
        assert new.pipeline_status == "INDEXED"
        assert new.supersedes_version_id == old_dvid  # 真实解析:226 supersedes 182
        assert new.logical_id == pg.get(DocVersion, old_dvid).logical_id  # revise 继承 logical

        # finalize 自动切换:旧版 182 → superseded,新版 226 effective
        assert pg.get(DocVersion, old_dvid).version_status == "superseded"
        assert new.version_status == "effective"
        assert all(c.chunk_status == "superseded" for c in pg.get_chunks(old_dvid))

        # 3) V4:默认 search 仅命中新版 226,旧版 182 不可见;--include-superseded 见 182
        q = ctx.embedding.embed(["上市公司信息披露义务"])[0]
        default_hits = _dvids(mio.search(q.dense, q.sparse, topk=50))
        assert new_dvid in default_hits, "新版 226 应被默认检索命中"
        assert old_dvid not in default_hits, "旧版 182 默认检索应不可见(已 superseded)"
        with_old = _dvids(mio.search(q.dense, q.sparse, topk=50, include_superseded=True))
        assert old_dvid in with_old, "--include-superseded 应见旧版 182"
    finally:
        _cleanup(pg, mio, batches)
