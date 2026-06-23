"""R2 变更查询编排(§6.2):定位制度 → 版本对回查 → 条款级 diff → 修订原因 → §10 契约。零 LLM。

红线:修订原因**仅来自 ``revision_notes``**,缺失则明示、**绝不推测**。定位用 R1 检索 top1(§9-Q1)。
``pg`` 为 ``pipeline.index.pg_io.PgIO``。
"""

from __future__ import annotations

from sqlalchemy import select

from common.pg_models import Chunk, DocVersion, RevisionNote
from query.change.version_diff import ClauseChange, diff_clauses
from query.contract import AnswerBlock, BlockType, Citation, QueryResult, RouteType
from query.generate.anchors import fetch_anchors
from query.retrieve.hybrid import drop_degraded

_NO_REASON = "修订说明未提供,无法给出官方修订原因。"
_BACKGROUND = "同期监管背景:未纳入本期。"
_KIND_LABEL = {"added": "新增", "removed": "删除", "changed": "修改"}


def resolve_version_pair(pg, dvid_hit: str):
    """命中版本 → 其 logical 的现行(effective)版本 current + current 的直接前驱(supersedes)。

    无 effective 回退命中版本;无前驱返回 ``(current, None)``;命中不存在返回 ``(None, None)``。
    """
    with pg.session() as s:
        hit = s.get(DocVersion, dvid_hit)
        if hit is None:
            return None, None
        current = (
            s.scalars(
                select(DocVersion).where(
                    DocVersion.logical_id == hit.logical_id,
                    DocVersion.version_status == "effective",
                )
            ).first()
            or hit
        )
        predecessor = (
            s.get(DocVersion, current.supersedes_version_id)
            if current.supersedes_version_id
            else None
        )
        return current, predecessor


def fetch_clause_chunks(pg, dvid: str) -> list[dict]:
    """某版本的条款级块(非 parent / 非 degraded / clause_path_norm 非空)。"""
    with pg.session() as s:
        rows = s.scalars(
            select(Chunk)
            .where(
                Chunk.doc_version_id == dvid,
                Chunk.is_parent.is_(False),
                Chunk.degraded.is_(False),
                Chunk.clause_path_norm.is_not(None),
            )
            .order_by(Chunk.seq)  # 稳定序:同条款多子块按 seq 聚合(version_diff)
        )
        return [
            {
                "clause_path_norm": c.clause_path_norm,
                "text": c.text,
                "chunk_id": c.chunk_id,
                "seq": c.seq,
            }
            for c in rows
        ]


def fetch_revision(pg, dvid: str):
    with pg.session() as s:
        return s.scalars(select(RevisionNote).where(RevisionNote.doc_version_id == dvid)).first()


def format_reason(revision) -> str:
    """修订原因:有 ``raw_text`` → 回查原文;无 → 明示缺失(绝不推测)。"""
    if revision is None or not (revision.raw_text or "").strip():
        return _NO_REASON
    return revision.raw_text.strip()


def _version_line(current, predecessor, n: int) -> str:
    title = getattr(current, "title", None) or "(未命名制度)"
    cur = f"{current.doc_version_id}({current.issue_date or '日期未知'},{current.version_status})"
    pred = f"{predecessor.doc_version_id}({predecessor.issue_date or '日期未知'})"
    return f"「{title}」版本变更:现行 {cur} ← 前驱 {pred}。共 {n} 处条款变更。"


def build_change_result(
    current, predecessor, changes: list[ClauseChange], reason: str, citations: list[Citation]
) -> QueryResult:
    table = (
        "\n".join(f"{_KIND_LABEL.get(c.kind, c.kind)} | {c.clause_path_norm}" for c in changes)
        or "(无条款级变更)"
    )
    return QueryResult(
        route_type=RouteType.CHANGE,
        answer_blocks=[
            AnswerBlock(BlockType.TEXT, _version_line(current, predecessor, len(changes))),
            AnswerBlock(BlockType.TABLE, table),
            AnswerBlock(BlockType.TEXT, f"变更原因:{reason}"),
            AnswerBlock(BlockType.TEXT, _BACKGROUND),
        ],
        citations=citations,
        confidence=0.0,  # ⚠ Q8 待标定
    )


def build_no_history(current) -> QueryResult:
    title = getattr(current, "title", None) or "(未命名制度)"
    return QueryResult(
        route_type=RouteType.CHANGE,
        answer_blocks=[AnswerBlock(BlockType.TEXT, f"「{title}」无历史版本可比(疑为首版)。")],
        confidence=0.0,
    )


def _locate_failed() -> QueryResult:
    return QueryResult(
        route_type=RouteType.CHANGE,
        answer_blocks=[
            AnswerBlock(BlockType.TEXT, "未能定位到相关制度,无法给出版本变更;请补充制度名称。")
        ],
        confidence=0.0,
    )


def answer_change(query: str, retriever, pg) -> QueryResult:
    """R2 主路径:定位 → 版本对 → diff → 修订原因 → 契约。"""
    cands = drop_degraded(retriever.retrieve(query))
    if not cands:
        return _locate_failed()
    current, predecessor = resolve_version_pair(pg, cands[0].doc_version_id)
    if current is None:
        return _locate_failed()
    if predecessor is None:
        return build_no_history(current)

    new_chunks = fetch_clause_chunks(pg, current.doc_version_id)
    changes = diff_clauses(fetch_clause_chunks(pg, predecessor.doc_version_id), new_chunks)
    reason = format_reason(fetch_revision(pg, current.doc_version_id))
    # 新增/修改条款 → 当前版本该条款首子块(按 seq)chunk_id → 四级引用
    path_to_cid: dict[str, str] = {}
    for c in new_chunks:  # new_chunks 已按 seq 升序
        path_to_cid.setdefault(c["clause_path_norm"], c["chunk_id"])
    cited = [
        path_to_cid[ch.clause_path_norm]
        for ch in changes
        if ch.kind in ("added", "changed") and ch.clause_path_norm in path_to_cid
    ]
    anchors = fetch_anchors(pg, cited)
    citations = [anchors[i] for i in cited if i in anchors]
    return build_change_result(current, predecessor, changes, reason, citations)
