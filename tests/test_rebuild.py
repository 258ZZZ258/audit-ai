"""A4 · rebuild 测试(连 PG + Milvus,**免模型**,合成向量)。

seed 一个"已索引"件(chunks + 冷备 + Milvus)→ 记 drop 前对该件向量的 top 查命中 → `run_rebuild`
(drop 全集 + 从 PG 冷备零编码全量重灌)→ 断言该件 count 恢复、全集 count == PG 全量、同查询命中集一致
(向量 bit 一致 → 重建无漂移,即 V6 "top10 一致")。注:rebuild 全局,亦把库内其他 PG 件一并回灌。
"""

import pytest
from sqlalchemy import delete, text
from ulid import ULID

from common.pg_models import Chunk, Document, DocVersion, ImportBatch, PipelineEvent
from pipeline.config import load_config
from pipeline.index import corpus_rows
from pipeline.index.milvus_io import MilvusIO, dense_to_bytes, sparse_to_bytes
from pipeline.index.object_store import ObjectStore
from pipeline.index.pg_io import PgIO
from pipeline.stage_base import StageContext
from pipeline.verify.rebuild import run_rebuild

# 唯一向量(区别于库内真实 BGE-M3 向量,使本件块在自查询中稳居 top)
DENSE = [float((i * 3) % 7) + 0.11 for i in range(1024)]
SPARSE = {"3": 0.9, "11": 0.5}


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
    bid, lid, dvid = "rb_" + str(ULID()), str(ULID()), str(ULID())
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
    mio.upsert(corpus_rows.rows_from_cold(pg, dvid))
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


def _topk_ids(mio, dvid, k=10):
    # 限本件向量自查询,取命中里属本件的 chunk_id 集(避开库内其他件干扰)
    res = mio.search(DENSE, SPARSE, topk=k)
    return {h["chunk_id"] for h in res.hits if h["doc_version_id"] == dvid}


def test_rebuild_reloads_from_cold_zero_encode(seeded):
    pg, mio, ctx, dvid, n = seeded
    before_ids = _topk_ids(mio, dvid)
    assert before_ids and mio.count(dvid) == n

    result = run_rebuild(ctx)
    assert result.after_count == result.chunks_reloaded  # 纯 insert,计数干净
    assert result.docs >= 1 and result.chunks_reloaded >= n

    # 该件恢复 + 同查询命中集一致(向量 bit 一致 → 无漂移,V6)
    assert mio.count(dvid) == n
    assert _topk_ids(mio, dvid) == before_ids
    # 全集 == PG 全量可回灌块(rebuild 后 Milvus = PG 权威;未嵌入 staging 块本就无投影,排除)
    pg_total = sum(len(corpus_rows.reloadable_chunks(pg, d)) for d in pg.chunk_doc_version_ids())
    assert mio.count() == pg_total


@pytest.fixture
def staging_doc(stack):
    """META_REVIEW 态件:有非 parent chunk 但 chunk_status=staging、**无冷备**、无 Milvus 投影。"""
    pg, mio, ctx = stack
    bid, lid, dvid = "rb_st_" + str(ULID()), str(ULID()), str(ULID())
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


def test_rows_from_cold_strict_vs_skip(staging_doc):
    """P2:有非 parent 块但冷备缺失时,strict 抛(s5/finalize 用),跳过式返 []（维护用)。"""
    from pipeline.index.corpus_rows import (
        ColdBackupIncomplete,
        rows_from_cold,
        rows_from_cold_strict,
    )
    pg, _mio, _ctx, sdvid, _n = staging_doc
    assert rows_from_cold(pg, sdvid) == []  # 跳过式:无冷备块跳过,不崩
    with pytest.raises(ColdBackupIncomplete):  # 严格式:有非 parent 块却缺冷备 → 抛
        rows_from_cold_strict(pg, sdvid, "effective")


def test_rebuild_skips_unembedded_without_data_loss(seeded, staging_doc):
    """回归(P1a):库内有 META_REVIEW 件(有块无冷备)时,rebuild 不得在 drop 后对 None 冷备反序列化崩。

    旧实现先 drop 全集再遍历,崩在半路 = 集合已空丢数据。应:不抛、已索引件块全恢复、未嵌入件零回灌。
    """
    pg, mio, ctx, dvid, n = seeded
    _pg, _mio, _ctx, sdvid, _sn = staging_doc
    before_ids = _topk_ids(mio, dvid)
    assert before_ids and mio.count(dvid) == n

    run_rebuild(ctx)  # 不应抛(旧实现遇 staging 件在 drop 后崩)

    # 已索引件:块全恢复、同查询命中一致(未因另一件缺冷备而被半路清空丢失)
    assert mio.count(dvid) == n
    assert _topk_ids(mio, dvid) == before_ids
    # 未嵌入件:无冷备 → 零回灌、Milvus 无该件投影
    assert mio.count(sdvid) == 0
    # 全集 == PG 可回灌块(staging 件的块被排除)
    pg_total = sum(len(corpus_rows.reloadable_chunks(pg, d)) for d in pg.chunk_doc_version_ids())
    assert mio.count() == pg_total
