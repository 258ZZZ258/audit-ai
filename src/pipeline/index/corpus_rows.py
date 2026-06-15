"""块 → Milvus ``CorpusRow`` 组装(PG chunk + 冷备向量 + 文档元数据);s5 索引与 finalize 切换共用。

抽出此处:``s5_embed_index`` 与 ``finalize`` 都要把"PG chunk + 冷备向量"映射成 Milvus 行,但两者是
stage、不得互相 import(CLAUDE.md)。放在 index/ 共享层即可复用同一映射,避免文档元数据
(corpus_type / perm_tag / issuer_level / …)两处重复且漂移。
"""

from __future__ import annotations

from pipeline.index.milvus_io import CorpusRow, dense_from_bytes, sparse_from_bytes
from pipeline.index.pg_io import PgIO
from pipeline.index.pg_models import Chunk, Document, DocVersion


def indexable_chunks(db: PgIO, dvid: str) -> list[Chunk]:
    """入 Milvus 的块:非 parent(parent=节级仅 PG;表格块入)。"""
    return [c for c in db.get_chunks(dvid) if not c.is_parent]


def _issuer_level(db: PgIO, dv: DocVersion) -> str:
    """dv.issuer(code 或 name)→ 字典 issuer_level;解析不出为空串(Milvus VARCHAR 不收 None)。"""
    v = (dv.issuer or "").strip()
    if not v:
        return ""
    for i in db.get_issuers():
        if i.code == v or i.name == v:
            return i.issuer_level or ""
    return ""


def build_rows(
    db: PgIO,
    dvid: str,
    chunks: list[Chunk],
    vectors: list[tuple[list[float], dict]],
    status: str | None,
) -> list[CorpusRow]:
    """chunk + (dense, sparse) + 文档元数据 → CorpusRow。

    ``status`` 指定则全行用之(staging/effective/superseded);**为 None 则按各 chunk 存储的
    ``chunk_status`` 还原**(reconcile/rebuild 重灌须保各块原状态,不强制单值)。
    """
    dv = db.get(DocVersion, dvid)
    doc = db.get(Document, dv.logical_id)
    corpus = (doc.corpus_type if doc else "") or ""  # corpus_type 在 Document(逻辑文档)
    issuer_level = _issuer_level(db, dv)
    return [
        CorpusRow(
            chunk_id=c.chunk_id, dense=dense, sparse=sparse,
            doc_version_id=dvid, corpus_type=corpus,
            status=(status if status is not None else c.chunk_status),
            perm_tag=dv.perm_tag or "", biz_domain=dv.biz_domain or "",
            issuer_level=issuer_level, clause_path=c.clause_path or "",
            page_start=c.page_start or 0, degraded=bool(c.degraded),
        )
        for c, (dense, sparse) in zip(chunks, vectors, strict=True)
    ]


def rows_from_cold(db: PgIO, dvid: str, status: str | None = None) -> list[CorpusRow]:
    """从 PG 冷备(dense_vec_cold / sparse_vec_cold)重建 CorpusRow——零重编码。

    ``status`` 指定:s5 index(→effective)/ finalize(→superseded)的"改标量重 upsert";
    ``status=None``(默认):按各 chunk 存储的 chunk_status 还原——reconcile/rebuild 重灌用。
    """
    chunks = indexable_chunks(db, dvid)
    vectors = [
        (dense_from_bytes(c.dense_vec_cold), sparse_from_bytes(c.sparse_vec_cold)) for c in chunks
    ]
    return build_rows(db, dvid, chunks, vectors, status)
