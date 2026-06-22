"""查询集成测试共享栈:连真 PG+Milvus+BGE-M3,ingest 一件内规到 INDEXED(B 模式自动放行)。

gate:PIPELINE_EMBEDDING_MODEL + PG + Milvus + soffice(同摄取侧 B 模式端到端)。任一不满足即 skip。
session 作用域:整批查询集成测试共用同一件 INDEXED 内规,结束反 FK 序清理 + 清 Milvus 投影。
"""

from __future__ import annotations

import os
from collections import namedtuple

import pytest
from docx import Document as Docx
from openpyxl import Workbook
from sqlalchemy import delete, select, text
from ulid import ULID

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
from pipeline import cli
from pipeline.config import load_config
from pipeline.index.embedding_client import EmbeddingClient
from pipeline.index.milvus_io import MilvusIO
from pipeline.index.object_store import ObjectStore
from pipeline.index.pg_io import PgIO
from pipeline.stage_base import StageContext
from pipeline.stages.s0_register import register_batch

_MANIFEST_COLS = [
    "filename",
    "title",
    "doc_number",
    "issuer",
    "perm_tag",
    "corpus_type",
    "biz_domain",
    "issue_date",
    "supersedes",
    "sub_type",
    "effective_date",
]

#: 稳定查询词(命中 ingest 件第三条「合同应当经法务审查并由授权人签署」)
QUERY_TEXT = "合同应当经法务审查并由授权人签署"

IndexedStack = namedtuple("IndexedStack", "pg mio ctx dvid query")


def _clean_internal_docx(tmp_path):
    """唯一无冲突内规件(首段=manifest 标题、body 无可抽文号 → L1 零冲突 → B 模式自动放行)。"""
    tag = str(ULID())
    d = tmp_path / ("q_" + tag[:8])
    d.mkdir()
    fn, title = "clean.docx", "合同管理办法"
    doc = Docx()
    doc.add_paragraph(title)
    doc.add_paragraph("第一章 总则")
    doc.add_paragraph("第一节 一般规定")  # 章→节→条:产出节级父块,使 §5.6 父块供证可验
    doc.add_paragraph(
        f"第一条 为加强本单位合同管理规范合同签订与履行流程根据有关规定制定本办法编号{tag}。"
    )
    doc.add_paragraph("第二条 本办法适用于本单位各部门及全体人员的合同签订与履行活动。")
    doc.add_paragraph("第二节 签订与履行")
    doc.add_paragraph("第三条 合同应当经法务审查并由授权人签署后方可对外签订生效并妥善归档备查。")
    doc.save(d / fn)
    wb = Workbook()
    wb.active.append(_MANIFEST_COLS)
    wb.active.append(
        [
            fn,
            title,
            f"测试第{tag[:6]}号",
            "INTERNAL",
            "内部",
            "P-INT",
            "LEGAL",
            None,
            None,
            "内规",
            None,
        ]
    )
    mp = d / "manifest.xlsx"
    wb.save(mp)
    return d, mp


@pytest.fixture(scope="session")
def indexed_stack(soffice, tmp_path_factory):
    if not os.environ.get("PIPELINE_EMBEDDING_MODEL"):
        pytest.skip("未设 PIPELINE_EMBEDDING_MODEL;查询集成跳过")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    cfg = load_config()
    cfg = cfg.model_copy(
        update={"toggles": cfg.toggles.model_copy(update={"auto_confirm_meta_no_conflict": True})}
    )
    pg = PgIO.from_config(cfg)
    try:
        with pg.session() as s:
            s.execute(text("select 1"))
    except Exception:
        pytest.skip("PG 不可达(demo up 未起)")
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

    tmp_path = tmp_path_factory.mktemp("q_ingest")
    d, m = _clean_internal_docx(tmp_path)
    bid = str(ULID())
    register_batch(ctx, bid, d, m)
    cli._drive_batch(pg, ctx, bid)  # B 模式:无人工放行自动到 INDEXED + finalize
    with pg.session() as s:
        dvids = [
            x.doc_version_id
            for x in s.scalars(select(DocVersion).where(DocVersion.batch_id == bid))
        ]
    assert dvids, "ingest 未产出 dvid"
    (dvid,) = dvids
    dv = pg.get(DocVersion, dvid)
    assert dv.pipeline_status == "INDEXED", f"未到 INDEXED:{dv.pipeline_status}"
    logical_id = dv.logical_id

    yield IndexedStack(pg, mio, ctx, dvid, QUERY_TEXT)

    # 反 FK 序清理 + Milvus 投影
    try:
        mio.delete(dvid)
        mio.flush()
    except Exception:
        pass
    with pg.session() as s:
        child_ids = select(Chunk.chunk_id).where(Chunk.doc_version_id == dvid)
        s.execute(delete(ClauseTag).where(ClauseTag.chunk_id.in_(child_ids)))
        s.execute(delete(Chunk).where(Chunk.doc_version_id == dvid))
        s.execute(delete(PipelineEvent).where(PipelineEvent.doc_version_id == dvid))
        s.execute(delete(RemediationRecord).where(RemediationRecord.doc_version_id == dvid))
        s.execute(delete(ReviewQueue).where(ReviewQueue.doc_version_id == dvid))
        s.execute(delete(DocVersion).where(DocVersion.doc_version_id == dvid))
        s.execute(delete(Document).where(Document.logical_id == logical_id))
        s.execute(delete(ImportBatch).where(ImportBatch.batch_id == bid))
    mio.disconnect()
