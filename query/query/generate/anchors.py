"""§7.3 四级锚点回查 + §5.6 父块供证。从 PG 权威表回查,**不用 Milvus 截断 text**。

四级:clause_id(=chunk_id) → 文档(标题/文号/版本 status) → clause_path → 页码。
父块供证:子块经 ``parent_chunk_id`` 取节级父块全文(供 LLM 完整上下文)。
``pg`` 形参为 ``pipeline.index.pg_io.PgIO``(提供 ``.session()`` / ``.get()``)。
"""

from __future__ import annotations

from sqlalchemy import select

from common.pg_models import Chunk, DocVersion
from query.contract import Citation


def fetch_anchors(pg, chunk_ids: list[str]) -> dict[str, Citation]:
    """批量回查 chunk_id → ``Citation``(四级锚点)。去重保序;未命中的 chunk_id 不在返回中。"""
    ids = list(dict.fromkeys(chunk_ids))  # 去重保序
    if not ids:
        return {}
    with pg.session() as s:
        chunks = {c.chunk_id: c for c in s.scalars(select(Chunk).where(Chunk.chunk_id.in_(ids)))}
        dvids = {c.doc_version_id for c in chunks.values()}
        dvs = (
            {
                d.doc_version_id: d
                for d in s.scalars(select(DocVersion).where(DocVersion.doc_version_id.in_(dvids)))
            }
            if dvids
            else {}
        )
    out: dict[str, Citation] = {}
    for cid in ids:
        c = chunks.get(cid)
        if c is None:
            continue
        dv = dvs.get(c.doc_version_id)
        out[cid] = Citation(
            clause_id=cid,
            doc_title=dv.title if dv else None,
            doc_no=dv.doc_number if dv else None,
            clause_path=c.clause_path,
            page_start=c.page_start,
            page_end=c.page_end,
            version=dv.issue_date.isoformat() if dv and dv.issue_date else None,
            status=dv.version_status if dv else None,
        )
    return out


def fetch_parent_text(pg, chunk_id: str) -> str | None:
    """取该子块的节级父块全文供证(§5.6);无父块返回 None。"""
    with pg.session() as s:
        c = s.get(Chunk, chunk_id)
        if c is None or not c.parent_chunk_id:
            return None
        parent = s.get(Chunk, c.parent_chunk_id)
        return parent.text if parent else None


def fetch_texts(pg, chunk_ids: list[str]) -> dict[str, str]:
    """批量回查 chunk_id → 全文(§7.3 权威源,供生成上下文)。去重;未命中不在返回中。"""
    ids = list(dict.fromkeys(chunk_ids))
    if not ids:
        return {}
    with pg.session() as s:
        return {c.chunk_id: c.text for c in s.scalars(select(Chunk).where(Chunk.chunk_id.in_(ids)))}
