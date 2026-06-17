"""A3 · 对账 reconcile 测试(连 PG + Milvus,**免模型**,合成向量)。

seed 一个"已索引"件(chunks + 冷备 + Milvus effective)→ 删部分 Milvus 实体造不平 →
`run_reconcile` 检出 E701 + 以 PG 冷备重灌 → 复检一致;已一致时 reconciled=False(no-op)。
"""

import pytest
from sqlalchemy import delete, text
from ulid import ULID

from common.pg_models import Chunk, Document, DocVersion, ImportBatch, PipelineEvent
from eval.reconcile import run_reconcile
from pipeline.config import load_config
from pipeline.index import corpus_rows
from pipeline.index.milvus_io import MilvusIO, dense_to_bytes, sparse_to_bytes
from pipeline.index.object_store import ObjectStore
from pipeline.index.pg_io import PgIO
from pipeline.stage_base import StageContext

DENSE = [float((i * 5) % 11) + 0.3 for i in range(1024)]
SPARSE = {"2": 0.8, "7": 0.4}


@pytest.fixture(scope="module")
def stack():
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
    ctx = StageContext(config=cfg, object_store=ObjectStore.from_config(cfg), db=pg, milvus=mio)
    yield pg, mio, ctx
    mio.disconnect()


@pytest.fixture
def seeded(stack):
    pg, mio, ctx = stack
    bid, lid, dvid = "rc_" + str(ULID()), str(ULID()), str(ULID())
    n = 3
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
        s.flush()
        for i in range(n):
            s.add(
                Chunk(
                    chunk_id=(f"{i}" + dvid)[:24], doc_version_id=dvid, text="第x条 内容",
                    clause_path="1", clause_path_norm="1", seq=i, page_start=1,
                    is_parent=False, is_table=False, chunk_status="effective",
                    dense_vec_cold=dense_to_bytes(DENSE), sparse_vec_cold=sparse_to_bytes(SPARSE),
                )
            )
    mio.upsert(corpus_rows.rows_from_cold(pg, dvid))  # status=None → 按存储 effective
    mio.flush()
    yield pg, mio, ctx, dvid, n
    mio.delete(dvid)
    mio.flush()
    with pg.session() as s:
        s.execute(delete(Chunk).where(Chunk.doc_version_id == dvid))
        s.execute(delete(PipelineEvent).where(PipelineEvent.doc_version_id == dvid))
        s.execute(delete(DocVersion).where(DocVersion.doc_version_id == dvid))
        s.execute(delete(Document).where(Document.logical_id == lid))
        s.execute(delete(ImportBatch).where(ImportBatch.batch_id == bid))


def test_reconcile_detects_mismatch_and_reloads(seeded):
    pg, mio, ctx, dvid, n = seeded
    assert mio.count(dvid) == n  # 初始一致
    mio.delete(dvid)  # 造不平:Milvus 少了
    mio.flush()
    assert mio.count(dvid) == 0

    r = run_reconcile(ctx, [dvid])
    rec = next(d for d in r.per_doc if d["dvid"] == dvid)
    assert rec["pg"] == n and rec["milvus"] == 0  # 检出不平
    assert rec["error_code"] == "E701" and rec["reconciled"] and rec["after"] == n  # 以 PG 重灌
    assert r.consistent
    assert mio.count(dvid) == n  # 复检一致


def test_reconcile_consistent_is_noop(seeded):
    pg, mio, ctx, dvid, n = seeded
    r = run_reconcile(ctx, [dvid])
    rec = next(d for d in r.per_doc if d["dvid"] == dvid)
    assert rec["pg"] == n and rec["milvus"] == n and rec["reconciled"] is False
    assert r.consistent


@pytest.fixture
def staging_doc(stack):
    """META_REVIEW 态件:有非 parent chunk 但 chunk_status=staging、无冷备、无 Milvus 投影。"""
    pg, mio, ctx = stack
    bid, lid, dvid = "rc_st_" + str(ULID()), str(ULID()), str(ULID())
    n = 3
    with pg.session() as s:
        s.add(ImportBatch(batch_id=bid, source_dir="x"))
        s.add(Document(logical_id=lid, corpus_type="P-INT"))
        s.flush()
        s.add(
            DocVersion(
                doc_version_id=dvid, logical_id=lid, batch_id=bid, source_format="docx",
                source_hash="h" + dvid[:8], raw_object_key="k", pipeline_status="META_REVIEW",
                perm_tag="内部", biz_domain="X", issuer="CSRC",
            )
        )
        s.flush()
        for i in range(n):
            s.add(
                Chunk(
                    chunk_id=(f"s{i}" + dvid)[:24], doc_version_id=dvid, text="第x条 内容",
                    clause_path="1", clause_path_norm="1", seq=i, page_start=1,
                    is_parent=False, is_table=False, chunk_status="staging",
                    dense_vec_cold=None, sparse_vec_cold=None,  # 未过 s5 嵌入:无冷备
                )
            )
    yield pg, mio, ctx, dvid, n
    with pg.session() as s:
        s.execute(delete(Chunk).where(Chunk.doc_version_id == dvid))
        s.execute(delete(PipelineEvent).where(PipelineEvent.doc_version_id == dvid))
        s.execute(delete(DocVersion).where(DocVersion.doc_version_id == dvid))
        s.execute(delete(Document).where(Document.logical_id == lid))
        s.execute(delete(ImportBatch).where(ImportBatch.batch_id == bid))


def test_reconcile_skips_unembedded_intermediate(staging_doc):
    """回归(P1b):META_REVIEW 件 PG 有块、Milvus 本就该空——应判一致、**不**误当缺失走重灌
    (旧实现以 indexable 计 pg=n≠milvus=0 → 进 rows_from_cold,对 None 冷备反序列化崩)。"""
    pg, mio, ctx, dvid, n = staging_doc
    assert mio.count(dvid) == 0  # 未嵌入 → 本就无投影
    r = run_reconcile(ctx, [dvid])  # 不应抛
    rec = next(d for d in r.per_doc if d["dvid"] == dvid)
    assert rec["pg"] == 0 and rec["milvus"] == 0  # 应有投影=reloadable(非 parent 且冷备齐全)=0
    assert rec["reconciled"] is False  # 一致 → 不重灌
    assert r.consistent
    assert mio.count(dvid) == 0  # 未被误灌
