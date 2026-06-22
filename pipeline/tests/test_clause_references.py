"""clause_references 集成测试 + 查询侧开发 fixture(连真 PG,不可达则 skip)。

本次只建表,**ref_resolver 填充逻辑未实现**(§6.7)。``SAMPLE_REFS`` 给出 R1–R4 四类样例行,
供查询侧 R1/R2 多跳确定性拦截开发/回归;``seed_clause_refs`` 把它们挂到一个真 chunk 上。
查询侧可直接 ``from pipeline.tests.test_clause_references import SAMPLE_REFS, seed_clause_refs``。
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete, select, text
from ulid import ULID

from common.pg_models import (
    Chunk,
    ClauseReference,
    Document,
    DocVersion,
    ImportBatch,
)
from pipeline.config import load_config
from pipeline.index.pg_io import PgIO

# R1–R4 四类样例(ref-specific 字段;chunk_id/doc_version_id 由 seed 时绑定)。
# R4 演示"内规正文引用外规"的 pending_target——外规尚未入库时 target_doc_version_id 留空。
SAMPLE_REFS: list[dict] = [
    {
        "surface_text": "本办法",
        "ref_type": "R1",
        "target_clause_path_norm": None,
        "resolution_status": "resolved",
    },
    {
        "surface_text": "前款",
        "ref_type": "R2",
        "target_clause_path_norm": "第三条第一款",
        "resolution_status": "resolved",
    },
    {
        "surface_text": "第十五条",
        "ref_type": "R3",
        "target_clause_path_norm": "第十五条",
        "resolution_status": "resolved",
    },
    {
        "surface_text": "《证券法》第一百九十六条",
        "ref_type": "R4",
        "target_clause_path_norm": "第一百九十六条",
        "resolution_status": "pending_target",
    },
]


def seed_clause_refs(pg: PgIO, dvid: str, chunk_id: str) -> int:
    """把 SAMPLE_REFS 四类行挂到 (dvid, chunk_id);返回写入行数。供查询侧开发复用。"""
    for r in SAMPLE_REFS:
        pg.add(ClauseReference(chunk_id=chunk_id, doc_version_id=dvid, method="rule", **r))
    return len(SAMPLE_REFS)


@pytest.fixture
def pg():
    io = PgIO.from_config(load_config())
    try:
        with io.session() as s:
            s.execute(text("select 1"))
    except Exception:
        pytest.skip("PG 不可达(demo up 未起)")
    return io


@pytest.fixture
def chunk_row(pg):
    """建 batch+document+doc_version+chunk,产出 (dvid, chunk_id);结束反 FK 序清理。"""
    bid = "test_" + str(ULID())[:10]
    lid = str(ULID())
    dvid = str(ULID())
    cid = str(ULID())[:24]
    pg.add(ImportBatch(batch_id=bid, source_dir="x"))
    pg.add(Document(logical_id=lid, corpus_type="P-INT"))
    pg.add(
        DocVersion(
            doc_version_id=dvid,
            logical_id=lid,
            batch_id=bid,
            source_format="docx",
            source_hash="h",
            raw_object_key="k",
        )
    )
    pg.add(
        Chunk(
            chunk_id=cid,
            doc_version_id=dvid,
            seq=0,
            text="第十五条 …前款…依照《证券法》第一百九十六条",
        )
    )
    yield dvid, cid
    with pg.session() as s:
        s.execute(delete(ClauseReference).where(ClauseReference.doc_version_id == dvid))
        s.execute(delete(Chunk).where(Chunk.doc_version_id == dvid))
        s.execute(delete(DocVersion).where(DocVersion.doc_version_id == dvid))
        s.execute(delete(Document).where(Document.logical_id == lid))
        s.execute(delete(ImportBatch).where(ImportBatch.batch_id == bid))


def test_clause_references_roundtrip(pg, chunk_row):
    dvid, cid = chunk_row
    assert seed_clause_refs(pg, dvid, cid) == 4
    with pg.session() as s:
        rows = list(
            s.scalars(select(ClauseReference).where(ClauseReference.doc_version_id == dvid))
        )
    # 四类齐全 + method 恒 rule
    assert {r.ref_type for r in rows} == {"R1", "R2", "R3", "R4"}
    assert all(r.method == "rule" for r in rows)
    # R4 跨文档:外规未入库 → pending_target,target_doc_version_id 留空
    r4 = next(r for r in rows if r.ref_type == "R4")
    assert r4.resolution_status == "pending_target"
    assert r4.target_doc_version_id is None
