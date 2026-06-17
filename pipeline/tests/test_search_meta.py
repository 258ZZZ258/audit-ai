"""C7 端到端集成测试:meta confirm 放行 → 推进至 INDEXED → search 四级引用。

gate:PIPELINE_EMBEDDING_MODEL(本地 BGE-M3)+ PG + Milvus,缺任一则 skip(绝不联网下载)。
经 typer CliRunner 真跑 ``demo meta confirm`` 与 ``demo search``:seed 一个停在 META_REVIEW 的 doc
(带 staging chunks + meta_confirm 队列行)→ confirm 走 approve→EMBEDDING→INDEXING→INDEXED →
search 命中且输出四级引用(文档+文号/条款/页码/版本+状态)。
"""

import os

import pytest
from sqlalchemy import delete, text
from typer.testing import CliRunner
from ulid import ULID

from common.pg_models import (
    Chunk,
    Document,
    DocVersion,
    ImportBatch,
    PipelineEvent,
    RemediationRecord,
    ReviewQueue,
)
from pipeline.cli import app
from pipeline.config import load_config
from pipeline.index.embedding_client import EmbeddingClient
from pipeline.index.milvus_io import MilvusIO
from pipeline.index.pg_io import PgIO
from pipeline.states import PipelineState as PS

runner = CliRunner()


@pytest.fixture(scope="module")
def stack():
    if not os.environ.get("PIPELINE_EMBEDDING_MODEL"):
        pytest.skip("未设 PIPELINE_EMBEDDING_MODEL(本地 BGE-M3);C7 端到端跳过")
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
    try:
        EmbeddingClient.from_config(cfg).embed(["探测"])
    except Exception as e:
        pytest.skip(f"BGE-M3 加载失败: {e}")
    yield pg, mio
    mio.disconnect()


@pytest.fixture
def seeded(stack):
    """seed META_REVIEW doc(2 非-parent staging chunk)+ meta_confirm 队列行。"""
    pg, mio = stack
    bid, lid, dvid, qid = "c7_" + str(ULID()), str(ULID()), str(ULID()), str(ULID())
    with pg.session() as s:
        s.add(ImportBatch(batch_id=bid, source_dir="x"))
        s.add(Document(logical_id=lid, corpus_type="P-INT", title="信息披露管理办法"))
        s.flush()
        s.add(
            DocVersion(
                doc_version_id=dvid, logical_id=lid, batch_id=bid, source_format="docx",
                source_hash="h" + dvid[:8], raw_object_key="k", title="信息披露管理办法",
                doc_number="证监会令第182号", pipeline_status=PS.META_REVIEW.value,
                perm_tag="内部", biz_domain="DISCLOSURE", issuer="CSRC",
            )
        )
        s.flush()
        rows = [
            ("1", "第一条 为加强信息披露管理,根据有关规定制定本办法。", "1/1"),
            ("2", "第二条 上市公司应当及时披露信息披露义务相关事项。", "1/2"),
        ]
        for suf, txt, norm in rows:
            s.add(
                Chunk(
                    chunk_id=(dvid[:22] + suf)[:24], doc_version_id=dvid, text=txt,
                    clause_path=norm, clause_path_norm=norm, seq=int(suf), page_start=1,
                    is_parent=False, is_table=False, chunk_status="staging",
                )
            )
        s.add(
            ReviewQueue(
                queue_id=qid, queue_type="meta_confirm", doc_version_id=dvid,
                reason="元数据待人工确认", evidence={"conflicts": []}, status="open",
            )
        )
    yield pg, mio, bid, dvid, qid
    mio.delete(dvid)
    mio.flush()
    with pg.session() as s:
        s.execute(delete(RemediationRecord).where(RemediationRecord.doc_version_id == dvid))
        s.execute(delete(ReviewQueue).where(ReviewQueue.doc_version_id == dvid))
        s.execute(delete(Chunk).where(Chunk.doc_version_id == dvid))
        s.execute(delete(PipelineEvent).where(PipelineEvent.doc_version_id == dvid))
        s.execute(delete(DocVersion).where(DocVersion.doc_version_id == dvid))
        s.execute(delete(Document).where(Document.logical_id == lid))
        s.execute(delete(ImportBatch).where(ImportBatch.batch_id == bid))


def test_meta_confirm_drives_to_indexed_then_search(seeded):
    pg, mio, bid, dvid, qid = seeded

    r = runner.invoke(app, ["meta", "confirm", qid])
    assert r.exit_code == 0, r.output
    assert "approve" in r.output and "INDEXED" in r.output
    assert pg.get(DocVersion, dvid).pipeline_status == "INDEXED"
    assert pg.get(ReviewQueue, qid).status == "closed"
    assert mio.count(dvid) == 2  # 两个非-parent 块入 Milvus

    r = runner.invoke(app, ["search", "信息披露义务", "--topk", "10"])
    assert r.exit_code == 0, r.output
    assert "信息披露管理办法" in r.output  # 文档(四级引用之一)
    assert "证监会令第182号" in r.output  # 文号
    assert "effective" in r.output  # 状态


def test_meta_confirm_batch(seeded):
    pg, mio, bid, dvid, qid = seeded
    r = runner.invoke(app, ["meta", "confirm", "--batch", bid])
    assert r.exit_code == 0, r.output
    assert "整批放行 1 件" in r.output
    assert pg.get(DocVersion, dvid).pipeline_status == "INDEXED"


def test_meta_confirm_closes_sibling_rows(seeded):
    # merge/split 件:s0 + s4 各写一条 meta_confirm。doc-centric 放行须一次迁移 + 全部关单,
    # 不留悬挂 open 行(否则 INDEXED 后 `meta list` 仍显示该件待确认)。
    pg, mio, bid, dvid, qid = seeded
    qid2 = str(ULID())
    with pg.session() as s:
        s.add(
            ReviewQueue(
                queue_id=qid2, queue_type="meta_confirm", doc_version_id=dvid,
                reason="demo 不支持的版本关系(split_replace),转人工",
                evidence={"conflicts": []}, status="open",
            )
        )
    r = runner.invoke(app, ["meta", "confirm", qid])
    assert r.exit_code == 0, r.output
    assert "+1 关联项" in r.output
    assert pg.get(DocVersion, dvid).pipeline_status == "INDEXED"
    assert pg.get(ReviewQueue, qid).status == "closed"
    assert pg.get(ReviewQueue, qid2).status == "closed"  # 关联行随之关单,不悬挂
