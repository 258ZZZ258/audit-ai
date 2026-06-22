"""T6:四级锚点 PG 回查 + 父块供证。

gate 见 conftest.indexed_stack(PIPELINE_EMBEDDING_MODEL + PG + Milvus + soffice)。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from common.pg_models import Chunk
from query.generate.anchors import fetch_anchors, fetch_parent_text


def _clause_chunks(pg, dvid: str):
    with pg.session() as s:
        return list(
            s.scalars(
                select(Chunk).where(
                    Chunk.doc_version_id == dvid,
                    Chunk.is_parent.is_(False),
                    Chunk.clause_path.is_not(None),
                )
            )
        )


def test_fetch_anchors_four_level(indexed_stack):
    pg, mio, ctx, dvid, query = indexed_stack
    ids = [c.chunk_id for c in _clause_chunks(pg, dvid)][:3]
    assert ids, "ingest 件应有条款级子块"

    anchors = fetch_anchors(pg, ids)
    assert set(anchors) <= set(ids)  # 未命中不臆造
    for cid in ids:
        cit = anchors[cid]
        assert cit.clause_id == cid
        assert cit.doc_title == "合同管理办法"   # 文档级回查(标题)
        assert cit.status == "effective"          # 版本状态(version_status)
        assert cit.clause_path is not None        # 条款路径回查到位
        assert cit.page_start is not None         # 页码锚点(soffice 渲染产出)


def test_fetch_anchors_empty_input(indexed_stack):
    pg, *_ = indexed_stack
    assert fetch_anchors(pg, []) == {}


def test_fetch_parent_text_supplies_section(indexed_stack):
    pg, mio, ctx, dvid, query = indexed_stack
    with pg.session() as s:
        child = s.scalars(
            select(Chunk).where(
                Chunk.doc_version_id == dvid,
                Chunk.parent_chunk_id.is_not(None),
            )
        ).first()
    if child is None:
        pytest.skip("该件无父子块(章节结构过简,无节级父块)")
    txt = fetch_parent_text(pg, child.chunk_id)
    assert txt and len(txt) > 0  # 父块全文供证(§5.6)
