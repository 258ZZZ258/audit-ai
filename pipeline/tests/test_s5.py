"""s5_embed_index 集成测试(连真 PG + Milvus + 本地 BGE-M3)。

gate:PIPELINE_EMBEDDING_MODEL(本地模型)+ PG + Milvus,缺任一则 skip。直接 seed PG chunks
(免跑 s1–s3),验证 embed→index 全链路到 INDEXED、冷备写入、parent 排除、staging→effective、可检索、
degraded 件终于 DEGRADED_INDEXED。
"""

import os

import pytest
from sqlalchemy import delete, text
from ulid import ULID

from common.pg_models import Chunk, Document, DocVersion, ImportBatch, PipelineEvent
from pipeline.config import load_config
from pipeline.index.embedding_client import EmbeddingClient
from pipeline.index.milvus_io import MilvusIO
from pipeline.index.object_store import ObjectStore
from pipeline.index.pg_io import PgIO
from pipeline.orchestrator import Orchestrator
from pipeline.stage_base import StageContext
from pipeline.stages import s5_embed_index as s5
from pipeline.states import PipelineState as PS


def _advance(pg, ctx, dvid):
    """经 orchestrator 推进本件(应用迁移):EMBEDDING→INDEXING→终态。"""
    orch = Orchestrator(pg, ctx, {PS.EMBEDDING: s5.embed, PS.INDEXING: s5.index})
    for _ in range(10):
        if not orch.step(pg.get(DocVersion, dvid)):
            break


@pytest.fixture(scope="module")
def worker():
    if not os.environ.get("PIPELINE_EMBEDDING_MODEL"):
        pytest.skip("未设 PIPELINE_EMBEDDING_MODEL(本地 BGE-M3);s5 真模型测试跳过")
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
        from pymilvus import utility

        utility.has_collection(cfg.milvus.collection)
    except Exception:
        pytest.skip("Milvus 不可达")
    mio.create_collection()
    emb = EmbeddingClient.from_config(cfg)
    try:
        emb.embed(["探测"])
    except Exception as e:
        pytest.skip(f"BGE-M3 加载失败: {e}")
    ctx = StageContext(
        config=cfg, object_store=ObjectStore.from_config(cfg), db=pg, embedding=emb, milvus=mio
    )
    yield pg, ctx, mio
    mio.disconnect()


@pytest.fixture
def seeded(worker):
    """seed 1 个 EMBEDDING 文档 + 2 非-parent + 1 parent chunk(staging),返回造档工具。"""
    pg, ctx, mio = worker
    bid, lid, dvid = "s5_" + str(ULID()), str(ULID()), str(ULID())

    def _make(degraded: bool) -> str:
        with pg.session() as s:
            s.add(ImportBatch(batch_id=bid, source_dir="x"))
            s.add(Document(logical_id=lid, corpus_type="P-INT"))
            s.flush()
            s.add(
                DocVersion(
                    doc_version_id=dvid, logical_id=lid, batch_id=bid, source_format="docx",
                    source_hash="h" + dvid[:8], raw_object_key="k",
                    pipeline_status=PS.EMBEDDING.value, degraded=degraded,
                    perm_tag="内部", biz_domain="DISCLOSURE", issuer="CSRC",
                )
            )
            s.flush()
            rows = [
                ("1", "第一条 为加强管理,根据有关规定制定本办法。", "1/1", False),
                ("2", "第二条 本办法适用于本单位各部门。", "1/2", False),
                ("p", "第一章 总则", "1", True),  # 父块:仅 PG,不入 Milvus
            ]
            for suf, txt, norm, is_parent in rows:
                s.add(
                    Chunk(
                        chunk_id=(dvid[:22] + suf)[:24], doc_version_id=dvid, text=txt,
                        clause_path=norm, clause_path_norm=norm, seq=int(suf, 36), page_start=1,
                        is_parent=is_parent, is_table=False, degraded=degraded,
                        chunk_status="staging",
                    )
                )
        return dvid

    ctx_state = {"make": _make}
    yield pg, ctx, mio, dvid, ctx_state
    mio.delete(dvid)
    mio.flush()
    with pg.session() as s:
        s.execute(delete(Chunk).where(Chunk.doc_version_id == dvid))
        s.execute(delete(PipelineEvent).where(PipelineEvent.doc_version_id == dvid))
        s.execute(delete(DocVersion).where(DocVersion.doc_version_id == dvid))
        s.execute(delete(Document).where(Document.logical_id == lid))
        s.execute(delete(ImportBatch).where(ImportBatch.batch_id == bid))


def test_embed_index_full_chain(seeded):
    pg, ctx, mio, dvid, st = seeded
    st["make"](degraded=False)
    _advance(pg, ctx, dvid)  # EMBEDDING → INDEXING → INDEXED

    assert pg.get(DocVersion, dvid).pipeline_status == "INDEXED"
    chunks = pg.get_chunks(dvid)
    nonparent = [c for c in chunks if not c.is_parent]
    assert all(c.dense_vec_cold and c.sparse_vec_cold for c in nonparent)  # 冷备写入
    assert all(c.dense_vec_cold is None for c in chunks if c.is_parent)  # 父块不嵌入
    assert mio.count(dvid) == len(nonparent) == 2  # parent 排除,PG 数 == Milvus 数
    assert all(c.chunk_status == "effective" for c in chunks)  # staging→effective

    q = ctx.embedding.embed(["管理办法 适用范围"])[0]
    res = mio.search(q.dense, q.sparse, topk=20)
    assert dvid in [h["doc_version_id"] for h in res.hits]  # effective 后可检索


def test_degraded_doc_finalizes_degraded_indexed(seeded):
    pg, ctx, mio, dvid, st = seeded
    st["make"](degraded=True)
    _advance(pg, ctx, dvid)
    assert pg.get(DocVersion, dvid).pipeline_status == "DEGRADED_INDEXED"
    assert all(c.degraded for c in pg.get_chunks(dvid))  # chunk 标 degraded
