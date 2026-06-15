"""D3 V5 幂等 + reprocess 集成测试(连 PG + Milvus)。

- test_verify_idempotency_stable:**免模型**——seed 一个"已索引"件(chunks+冷备+Milvus effective)+
  磁盘文件(SHA 匹配)+ manifest,跑 `check_idempotency`:第二次 ingest 走 s0 SHA 去重(不新建 doc),
  断言 chunk_id 集合 + Milvus 实体数不变、写 duplicate_ingest 留痕。
- test_reprocess_deterministic:**模型门控**——真实 182 PDF ingest+index→reprocess→断言回到 INDEXED 且
  chunk_id 集合 + Milvus 计数不变(确定性 chunk_id 使全量重跑幂等)。
"""

import hashlib
import os

import pytest
from openpyxl import Workbook
from sqlalchemy import delete, select, text
from typer.testing import CliRunner
from ulid import ULID

from pipeline import cli
from pipeline.config import load_config
from pipeline.index import corpus_rows
from pipeline.index.embedding_client import EmbeddingClient
from pipeline.index.milvus_io import MilvusIO, dense_to_bytes, sparse_to_bytes
from pipeline.index.object_store import ObjectStore
from pipeline.index.pg_io import PgIO
from pipeline.index.pg_models import (
    Chunk,
    Document,
    DocVersion,
    ImportBatch,
    PipelineEvent,
    RemediationRecord,
    ReviewQueue,
)
from pipeline.stage_base import StageContext
from pipeline.verify.idempotency import check_idempotency

runner = CliRunner()

DENSE = [float((i * 7) % 13) + 0.5 for i in range(1024)]
SPARSE = {"1": 0.9, "5": 0.3, "42": 0.6}
_COLS = [
    "filename", "title", "doc_number", "issuer", "perm_tag",
    "corpus_type", "biz_domain", "issue_date", "supersedes",
]


def _pg_milvus():
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
    return cfg, pg, mio


@pytest.fixture
def pgmilvus():
    """PG + Milvus(免模型);ctx 无 embedding(idempotency 不重嵌入)。"""
    cfg, pg, mio = _pg_milvus()
    ctx = StageContext(config=cfg, object_store=ObjectStore.from_config(cfg), db=pg, milvus=mio)
    yield pg, mio, ctx
    mio.disconnect()


@pytest.fixture(scope="module")
def model_stack():
    """PG + Milvus + 本地 BGE-M3(reprocess 重跑 s5 需嵌入)。"""
    if not os.environ.get("PIPELINE_EMBEDDING_MODEL"):
        pytest.skip("未设 PIPELINE_EMBEDDING_MODEL;reprocess 端到端跳过")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    cfg, pg, mio = _pg_milvus()
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


def _write_manifest(path, filename: str) -> None:
    wb = Workbook()
    ws = wb.active
    ws.append(_COLS)
    row = [filename, "幂等测试件", "测试第1号", "CSRC", "内部", "P-INT", "DISCLOSURE", None, None]
    ws.append(row)
    wb.save(path)


def test_verify_idempotency_stable(pgmilvus, tmp_path):
    pg, mio, ctx = pgmilvus
    # 磁盘文件(任意字节)+ manifest;seed 一个 SHA 匹配的"已索引"件
    d = tmp_path / "batch"
    d.mkdir()
    content = b"%PDF-1.4 idempotency fixture\n" + bytes(range(256))
    (d / "doc.pdf").write_bytes(content)
    _write_manifest(d / "manifest.xlsx", "doc.pdf")
    sha = hashlib.sha256(content).hexdigest()
    bid, lid, dvid = "idem_" + str(ULID()), str(ULID()), str(ULID())
    with pg.session() as s:
        s.add(ImportBatch(batch_id=bid, source_dir=str(d)))
        s.add(Document(logical_id=lid, corpus_type="P-INT", title="幂等测试件"))
        s.flush()
        s.add(
            DocVersion(
                doc_version_id=dvid, logical_id=lid, batch_id=bid, source_format="pdf",
                source_hash=sha, raw_object_key="k", source_filename="doc.pdf",
                pipeline_status="INDEXED", perm_tag="内部", biz_domain="DISCLOSURE", issuer="CSRC",
            )
        )
        s.flush()
        for suf in ("a", "b"):
            s.add(
                Chunk(
                    chunk_id=(suf + dvid)[:24], doc_version_id=dvid, text=f"第{suf}条 内容。",
                    clause_path=f"1/{suf}", clause_path_norm=f"1/{suf}", seq=1, page_start=1,
                    is_parent=False, is_table=False, chunk_status="effective",
                    dense_vec_cold=dense_to_bytes(DENSE), sparse_vec_cold=sparse_to_bytes(SPARSE),
                )
            )
    mio.upsert(corpus_rows.rows_from_cold(pg, dvid, "effective"))
    mio.flush()

    try:
        report = check_idempotency(ctx, d, d / "manifest.xlsx")
        assert report.passed, report.lines
        # 第二次 ingest 未新建 doc_version(SHA 去重),仍只有 1 个该 SHA 的 doc
        with pg.session() as s:
            n = len(list(s.scalars(select(DocVersion).where(DocVersion.source_hash == sha))))
        assert n == 1
    finally:
        for x in (dvid,):
            mio.delete(x)
        mio.flush()
        with pg.session() as s:
            s.execute(delete(Chunk).where(Chunk.doc_version_id == dvid))
            s.execute(delete(PipelineEvent).where(PipelineEvent.doc_version_id == dvid))
            s.execute(delete(DocVersion).where(DocVersion.doc_version_id == dvid))
            s.execute(delete(Document).where(Document.logical_id == lid))
            # 删两个批次:seed 的 + check_idempotency 第二次 ingest 建的(source_dir 同为临时目录)
            s.execute(delete(ImportBatch).where(ImportBatch.source_dir == str(d)))


def test_reprocess_deterministic(model_stack, soffice, tmp_path, unique_docx, ingest_index):
    pg, mio, ctx = model_stack
    d, m = unique_docx(tmp_path)  # 自造唯一 docx:隔离健壮,避开既有数据 SHA 去重(需 soffice 渲染)
    bid, dvids = ingest_index(pg, ctx, d, m)
    (dvid,) = dvids
    try:
        assert pg.get(DocVersion, dvid).pipeline_status == "INDEXED"
        before_ids = {c.chunk_id for c in pg.get_chunks(dvid)}
        before_count = mio.count(dvid)
        assert before_ids and before_count > 0

        r = runner.invoke(cli.app, ["reprocess", dvid])
        assert r.exit_code == 0, r.output
        assert pg.get(DocVersion, dvid).pipeline_status == "INDEXED"  # 重跑回到 INDEXED
        assert {c.chunk_id for c in pg.get_chunks(dvid)} == before_ids  # chunk_id 集合不变(确定性)
        assert mio.count(dvid) == before_count  # Milvus 实体数不变
    finally:
        mio.delete(dvid)
        mio.flush()
        with pg.session() as s:
            dvs = list(s.scalars(select(DocVersion).where(DocVersion.batch_id == bid)))
            lids = {x.logical_id for x in dvs}
            s.execute(delete(RemediationRecord).where(RemediationRecord.doc_version_id == dvid))
            s.execute(delete(ReviewQueue).where(ReviewQueue.doc_version_id == dvid))
            s.execute(delete(Chunk).where(Chunk.doc_version_id == dvid))
            s.execute(delete(PipelineEvent).where(PipelineEvent.doc_version_id == dvid))
            s.execute(delete(DocVersion).where(DocVersion.doc_version_id == dvid))
            s.execute(delete(Document).where(Document.logical_id.in_(lids)))
            s.execute(delete(ImportBatch).where(ImportBatch.batch_id == bid))
