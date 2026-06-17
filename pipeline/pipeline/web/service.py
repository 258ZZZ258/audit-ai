"""Service layer shared by the demo web workbench.

The web UI is intentionally a thin shell over the existing domain functions: it reads from PG as
authority, treats Milvus as projection, and uses the same queue/state-machine paths as the CLI.
"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from sqlalchemy import select
from ulid import ULID

from common.manifest import REQUIRED_COLUMNS
from common.pg_models import (
    Chunk,
    ClauseTag,
    Document,
    DocVersion,
    ImportBatch,
    PipelineEvent,
    ReviewQueue,
)
from pipeline import cli
from pipeline.queue import dispose
from pipeline.stages.s0_register import register_batch
from pipeline.verify.anchor_replay import run_replay
from pipeline.verify.rebuild import run_rebuild
from pipeline.verify.reconcile import run_reconcile
from pipeline.verify.report import build_report
from pipeline.verify.smoke import run_smoke

REPO_ROOT = Path(__file__).resolve().parents[3]
UPLOAD_ROOT = REPO_ROOT / "_web_uploads"
NODE_DEFS = [
    {
        "key": "S0",
        "label": "登记入库",
        "states": {"REGISTERED"},
        "artifacts": {"raw"},
    },
    {
        "key": "S1",
        "label": "解析抽取",
        "states": {"PARSING", "PARSE_FAILED", "QC_PENDING"},
        "artifacts": {"rendition", "ir"},
    },
    {
        "key": "S2",
        "label": "质量门禁",
        "states": {"QC_PENDING", "QC_FAILED", "QUARANTINED"},
        "artifacts": set(),
    },
    {
        "key": "S3",
        "label": "结构化分块",
        "states": {"STRUCTURING", "META_REVIEW"},
        "artifacts": {"chunks"},
    },
    {
        "key": "S4",
        "label": "元数据确认",
        "states": {"META_REVIEW", "EMBEDDING"},
        "artifacts": set(),
    },
    {
        "key": "S5",
        "label": "向量化与索引",
        "states": {"EMBEDDING", "INDEXING", "INDEXED", "DEGRADED_INDEXED"},
        "artifacts": {"milvus"},
    },
]
_FAILED_STATES = {
    "PARSE_FAILED",
    "QC_FAILED",
    "QUARANTINED",
    "REJECTED",
}
_NODE_ORDER = {node["key"]: i for i, node in enumerate(NODE_DEFS)}


@dataclass(frozen=True)
class UploadedFile:
    filename: str
    data: bytes


# ── 共享上下文缓存(模型/Milvus 连接复用,避免每请求重载 ~2GB BGE-M3 + 重连)──────────────
# 单进程 ThreadingHTTPServer 下足够:PgIO 每调用开新 session(线程安全),Milvus 用全局 alias,
# 嵌入模型只在首个 search/approve 请求懒载一次后复用。并发推理量小(人工点选),可接受。
_CTX: dict[str, tuple] = {}


def _shared(kind: str, builder) -> tuple:
    if kind not in _CTX:
        _CTX[kind] = builder()
    return _CTX[kind]


def _light() -> tuple:
    return _shared("light", cli._context)


def _worker() -> tuple:
    return _shared("worker", cli._worker_context)


def _pgm() -> tuple:
    return _shared("pgm", cli._pg_milvus_context)


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return value


@dataclass(frozen=True)
class ArtifactFile:
    filename: str
    content_type: str
    data: bytes


def _doc_payload(
    dv: DocVersion,
    doc: Document | None = None,
    *,
    chunk_count: int | None = None,
) -> dict[str, Any]:
    title = dv.title or (doc.title if doc else None) or dv.source_filename or dv.doc_version_id
    return {
        "doc_version_id": dv.doc_version_id,
        "logical_id": dv.logical_id,
        "batch_id": dv.batch_id,
        "title": title,
        "source_filename": dv.source_filename,
        "source_format": dv.source_format,
        "pipeline_status": dv.pipeline_status,
        "version_status": dv.version_status,
        "degraded": bool(dv.degraded),
        "perm_tag": dv.perm_tag,
        "biz_domain": dv.biz_domain,
        "issuer": dv.issuer,
        "doc_number": dv.doc_number,
        "issue_date": _jsonable(dv.issue_date),
        "supersedes_version_id": dv.supersedes_version_id,
        "version_relation": dv.version_relation,
        "last_error_code": dv.last_error_code,
        "corpus_type": doc.corpus_type if doc else None,
        "raw_object_key": dv.raw_object_key,
        "rendition_object_key": dv.rendition_object_key,
        "ir_object_key": dv.ir_object_key,
        "chunk_count": chunk_count,
    }


def _batch_payload(batch: ImportBatch, docs: list[DocVersion]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for d in docs:
        counts[d.pipeline_status] = counts.get(d.pipeline_status, 0) + 1
    return {
        "batch_id": batch.batch_id,
        "source_dir": batch.source_dir,
        "manifest_path": batch.manifest_path,
        "created_at": _jsonable(batch.created_at),
        "doc_count": len(docs),
        "status_counts": counts,
        "has_report": batch.report is not None,
    }


def overview() -> dict[str, Any]:
    pg, _ctx = _light()
    with pg.session() as s:
        docs = list(s.scalars(select(DocVersion)))
        batches = list(s.scalars(select(ImportBatch).order_by(ImportBatch.created_at.desc())))
        queues = list(s.scalars(select(ReviewQueue).order_by(ReviewQueue.created_at.desc())))
    state_counts = {k: v for k, v in sorted(_count(d.pipeline_status for d in docs).items())}
    open_queues = [q for q in queues if q.status == "open"]
    recent_batches = []
    for b in batches[:8]:
        recent_batches.append(_batch_payload(b, [d for d in docs if d.batch_id == b.batch_id]))
    return {
        "state_counts": state_counts,
        "doc_count": len(docs),
        "batch_count": len(batches),
        "open_queue_count": len(open_queues),
        "indexed_count": sum(1 for d in docs if d.pipeline_status in cli._INDEXED_STATES),
        "recent_batches": recent_batches,
        "open_queue": [_queue_payload(q) for q in open_queues[:8]],
    }


def _count(values) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return out


def batches() -> list[dict[str, Any]]:
    pg, _ctx = _light()
    with pg.session() as s:
        rows = list(s.scalars(select(ImportBatch).order_by(ImportBatch.created_at.desc())))
        docs = list(s.scalars(select(DocVersion)))
    return [_batch_payload(b, [d for d in docs if d.batch_id == b.batch_id]) for b in rows]


def batch_detail(batch_id: str) -> dict[str, Any]:
    pg, _ctx = _light()
    with pg.session() as s:
        batch = s.get(ImportBatch, batch_id)
        if batch is None:
            raise KeyError(batch_id)
        docs = list(
            s.scalars(
                select(DocVersion)
                .where(DocVersion.batch_id == batch_id)
                .order_by(DocVersion.created_at)
            )
        )
        logical_ids = [d.logical_id for d in docs]
        doc_rows = {
            d.logical_id: d
            for d in s.scalars(select(Document).where(Document.logical_id.in_(logical_ids or [""])))
        }
        chunk_counts = _chunk_counts(s, [d.doc_version_id for d in docs])
    return {
        **_batch_payload(batch, docs),
        "report": _jsonable(batch.report),
        "docs": [
            _doc_payload(
                d,
                doc_rows.get(d.logical_id),
                chunk_count=chunk_counts.get(d.doc_version_id, 0),
            )
            for d in docs
        ],
    }


def _queue_payload(q: ReviewQueue) -> dict[str, Any]:
    return {
        "queue_id": q.queue_id,
        "queue_type": q.queue_type,
        "doc_version_id": q.doc_version_id,
        "reason": q.reason,
        "evidence": _jsonable(q.evidence),
        "status": q.status,
        "disposition": q.disposition,
        "operator": q.operator,
        "processed_at": _jsonable(q.processed_at),
        "created_at": _jsonable(q.created_at),
    }


def queue_items(show_all: bool = False) -> list[dict[str, Any]]:
    pg, _ctx = _light()
    with pg.session() as s:
        q = select(ReviewQueue)
        if not show_all:
            q = q.where(ReviewQueue.status == "open")
        rows = list(s.scalars(q.order_by(ReviewQueue.created_at.desc())))
    return [_queue_payload(r) for r in rows]


def doc_detail(doc_version_id: str) -> dict[str, Any]:
    pg, ctx = _light()
    with pg.session() as s:
        dv = s.get(DocVersion, doc_version_id)
        if dv is None:
            raise KeyError(doc_version_id)
        doc = s.get(Document, dv.logical_id)
        chunks = list(
            s.scalars(
                select(Chunk).where(Chunk.doc_version_id == doc_version_id).order_by(Chunk.seq)
            )
        )
        events = list(
            s.scalars(
                select(PipelineEvent)
                .where(PipelineEvent.doc_version_id == doc_version_id)
                .order_by(PipelineEvent.id)
            )
        )
        queues = list(
            s.scalars(
                select(ReviewQueue)
                .where(ReviewQueue.doc_version_id == doc_version_id)
                .order_by(ReviewQueue.created_at)
            )
        )
        chunk_ids = [c.chunk_id for c in chunks]
        tags = list(
            s.scalars(select(ClauseTag).where(ClauseTag.chunk_id.in_(chunk_ids or [""])))
        )
    tags_by_chunk: dict[str, list[dict[str, Any]]] = {}
    for t in tags:
        tags_by_chunk.setdefault(t.chunk_id, []).append(
            {"tag_type": t.tag_type, "tag_value": t.tag_value, "evidence": t.evidence}
        )
    store = ctx.object_store
    artifacts = _artifact_payloads(dv, store)
    events_payload = [
        {
            "id": e.id,
            "from_state": e.from_state,
            "to_state": e.to_state,
            "error_code": e.error_code,
            "actor": e.actor,
            "detail": _jsonable(e.detail),
            "created_at": _jsonable(e.created_at),
        }
        for e in events
    ]
    chunk_payload = [
        {
            "chunk_id": c.chunk_id,
            "seq": c.seq,
            "clause_path": c.clause_path,
            "page_start": c.page_start,
            "page_end": c.page_end,
            "token_count": c.token_count,
            "is_parent": c.is_parent,
            "is_table": c.is_table,
            "oversize": c.oversize,
            "degraded": c.degraded,
            "chunk_status": c.chunk_status,
            "has_dense_cold": c.dense_vec_cold is not None,
            "has_sparse_cold": c.sparse_vec_cold is not None,
            "text": (c.text or "")[:1200],
            "tags": tags_by_chunk.get(c.chunk_id, []),
        }
        for c in chunks
    ]
    return {
        "doc": _doc_payload(dv, doc, chunk_count=len(chunks)),
        "artifacts": artifacts,
        "nodes": _node_payloads(dv, events_payload, queues, artifacts, chunk_payload),
        "events": events_payload,
        "queue": [_queue_payload(q) for q in queues],
        "chunks": chunk_payload,
    }


def _chunk_counts(session, doc_version_ids: list[str]) -> dict[str, int]:
    if not doc_version_ids:
        return {}
    rows = session.execute(
        select(Chunk.doc_version_id, Chunk.chunk_id).where(
            Chunk.doc_version_id.in_(doc_version_ids)
        )
    )
    counts: dict[str, int] = {}
    for dvid, _chunk_id in rows:
        counts[dvid] = counts.get(dvid, 0) + 1
    return counts


def _artifact_payloads(dv: DocVersion, store) -> list[dict[str, Any]]:
    candidates = [
        ("raw", dv.raw_object_key),
        ("rendition", dv.rendition_object_key),
        ("ir", store.ir_key(dv.doc_version_id)),
    ]
    payloads = []
    for kind, key in candidates:
        exists = bool(key and store.exists(key))
        payloads.append(
            {
                "kind": kind,
                "key": key,
                "exists": exists,
                "url": f"/api/docs/{dv.doc_version_id}/artifacts/{kind}" if exists else None,
            }
        )
    return payloads


def _node_payloads(
    dv: DocVersion,
    events: list[dict[str, Any]],
    queues: list[ReviewQueue],
    artifacts: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    current_node = _state_node(dv.pipeline_status)
    artifact_ready = {a["kind"] for a in artifacts if a["exists"]}
    if chunks:
        artifact_ready.add("chunks")
    if dv.pipeline_status in cli._INDEXED_STATES:
        artifact_ready.add("milvus")
    open_queues = [q for q in queues if q.status == "open"]
    nodes = []
    for node in NODE_DEFS:
        event_rows = [e for e in events if _state_node(e["to_state"]) == node["key"]]
        status = _node_status(dv.pipeline_status, current_node, node["key"], open_queues)
        ready = sorted(artifact_ready & node["artifacts"])
        nodes.append(
            {
                "key": node["key"],
                "label": node["label"],
                "status": status,
                "artifacts": ready,
                "event_count": len(event_rows),
                "last_event_at": event_rows[-1]["created_at"] if event_rows else None,
                "last_error_code": event_rows[-1]["error_code"] if event_rows else None,
            }
        )
    return nodes


def _node_status(
    pipeline_status: str,
    current_node: str | None,
    node_key: str,
    open_queues: list[ReviewQueue],
) -> str:
    if pipeline_status in cli._INDEXED_STATES:
        return "done"
    if pipeline_status == "REJECTED":
        return "failed" if node_key == "S2" else "done"
    if current_node is None:
        return "pending"
    if node_key == current_node:
        if any(_state_node(q.queue_type) == node_key for q in open_queues):
            return "waiting"
        if pipeline_status in _FAILED_STATES:
            return "failed"
        if pipeline_status == "META_REVIEW":
            return "waiting"
        return "running"
    return "done" if _NODE_ORDER[node_key] < _NODE_ORDER[current_node] else "pending"


def _state_node(value: str | None) -> str | None:
    if value is None:
        return None
    if value == "qc_fix" or value == "quarantine":
        return "S2"
    if value == "meta_confirm":
        return "S4"
    for node in NODE_DEFS:
        if value in node["states"]:
            return node["key"]
    return None


def artifact_file(doc_version_id: str, kind: str) -> ArtifactFile:
    pg, ctx = _light()
    with pg.session() as s:
        dv = s.get(DocVersion, doc_version_id)
        if dv is None:
            raise KeyError(doc_version_id)
    key = {
        "raw": dv.raw_object_key,
        "rendition": dv.rendition_object_key,
        "ir": ctx.object_store.ir_key(doc_version_id),
    }.get(kind)
    if not key or not ctx.object_store.exists(key):
        raise KeyError(f"{doc_version_id}:{kind}")
    data = ctx.object_store.get(key)
    suffix = Path(key).suffix.lower()
    content_type = {
        ".json": "application/json; charset=utf-8",
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }.get(suffix, "application/octet-stream")
    source_name = Path(dv.source_filename or doc_version_id).stem
    filename = {
        "raw": dv.source_filename or f"{doc_version_id}{suffix}",
        "rendition": f"{source_name}.rendition.pdf",
        "ir": f"{source_name}.ir.json",
    }[kind]
    return ArtifactFile(filename=filename, content_type=content_type, data=data)


def _write_auto_manifest(
    batch_dir: Path,
    files: list[UploadedFile],
    *,
    corpus_type: str,
    perm_tag: str,
    biz_domain: str,
    issuer: str,
) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.append(REQUIRED_COLUMNS)
    for f in files:
        suffix = Path(f.filename).suffix.lower()
        inferred_corpus = "P-EXT" if suffix == ".pdf" and corpus_type == "auto" else corpus_type
        if inferred_corpus == "auto":
            inferred_corpus = "P-INT"
        ws.append(
            [
                f.filename,
                Path(f.filename).stem,
                "",
                issuer,
                perm_tag,
                inferred_corpus,
                biz_domain,
                "",
                "",
            ]
        )
    manifest = batch_dir / "manifest.xlsx"
    wb.save(manifest)
    return manifest


def ingest_upload(
    files: list[UploadedFile],
    *,
    manifest: UploadedFile | None = None,
    corpus_type: str = "auto",
    perm_tag: str = "内部",
    biz_domain: str = "GENERAL",
    issuer: str = "DEMO",
) -> dict[str, Any]:
    docs = [f for f in files if Path(f.filename).suffix.lower() in {".pdf", ".docx"}]
    if not docs:
        raise ValueError("至少上传一个 .pdf 或 .docx 文件")
    batch_id = str(ULID())
    batch_dir = UPLOAD_ROOT / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)
    for f in docs:
        target = batch_dir / Path(f.filename).name
        target.write_bytes(f.data)
    if manifest is not None:
        manifest_path = batch_dir / Path(manifest.filename).name
        manifest_path.write_bytes(manifest.data)
    else:
        manifest_path = _write_auto_manifest(
            batch_dir,
            docs,
            corpus_type=corpus_type,
            perm_tag=perm_tag,
            biz_domain=biz_domain,
            issuer=issuer,
        )

    pg, ctx = _light()
    if ctx.config.toggles.auto_confirm_meta_no_conflict:  # B 模式:需 worker 上下文过 s5+finalize
        pg, ctx = _worker()
    report = register_batch(ctx, batch_id, batch_dir, manifest_path)
    if not report.accepted:
        raise ValueError(report.reject_reason)
    steps = cli._drive_batch(pg, ctx, batch_id)  # B 模式无冲突新件直达 INDEXED + finalize 扫尾
    return {
        "batch_id": batch_id,
        "steps": steps,
        "warnings": report.warnings,
        "outcomes": [asdict(o) for o in report.outcomes],
        "batch": batch_detail(batch_id),
    }


def dispose_queue(queue_id: str, disposition: str, operator: str = "web") -> dict[str, Any]:
    pg, ctx = _light()
    # B 模式下 fix/degrade/release 重入会自动越过 META_REVIEW、需 s5 到终态 → 用 worker 上下文,
    # 否则文档搁浅 EMBEDDING 却返回成功(B1)。_advance_one 过渡态守卫兜底,搁浅 → error → 抛出。
    b_mode = ctx.config.toggles.auto_confirm_meta_no_conflict
    if b_mode and disposition in cli._REENTRANT_DISPOSITIONS:
        pg, ctx = _worker()
    outcome = dispose(pg, queue_id, disposition, operator=operator)
    steps, final, error = cli._advance_one(pg, ctx, outcome.doc_version_id)
    if error is not None:
        raise RuntimeError(error)
    return {
        "outcome": asdict(outcome),
        "steps": steps,
        "final": final,
        "doc": doc_detail(outcome.doc_version_id)["doc"],
    }


def approve_meta(
    queue_id: str | None = None,
    batch_id: str | None = None,
    operator: str = "web",
) -> dict:
    if bool(queue_id) == bool(batch_id):
        raise ValueError("需且仅需指定 queue_id 或 batch_id")
    pg, ctx = _worker()
    if batch_id:
        with pg.session() as s:
            rows = list(
                s.scalars(
                    select(ReviewQueue)
                    .join(DocVersion, DocVersion.doc_version_id == ReviewQueue.doc_version_id)
                    .where(ReviewQueue.queue_type == "meta_confirm")
                    .where(ReviewQueue.status == "open")
                    .where(DocVersion.batch_id == batch_id)
                    .order_by(ReviewQueue.created_at)
                )
            )
        dvids = list(dict.fromkeys(r.doc_version_id for r in rows))
    else:
        with pg.session() as s:
            q = s.get(ReviewQueue, queue_id)
            if q is None:
                raise KeyError(queue_id)
            dvids = [q.doc_version_id]
    results = []
    for dvid in dvids:
        ok = cli._approve_doc(pg, ctx, dvid, operator)
        results.append({"doc_version_id": dvid, "ok": ok})
    if any(not r["ok"] for r in results):
        raise RuntimeError("部分文档未达 INDEXED")
    return {"results": results}


def reprocess_doc(doc_version_id: str, operator: str = "web") -> dict[str, Any]:
    """复用共享核心 ``cli.reprocess_to_indexed``(不再复刻 CLI 逻辑)。

    抛 KeyError(不存在)/ ValueError(态不可)/ RuntimeError(清理失败 / 未达 INDEXED),由 HTTP 层翻译。
    """
    pg, ctx = _worker()
    final = cli.reprocess_to_indexed(pg, ctx, doc_version_id, operator)
    return {"doc_version_id": doc_version_id, "final": final}


def run_verify(name: str, batch_id: str | None = None) -> dict[str, Any]:
    if name == "rebuild":
        _pg, ctx = _pgm()
        return {"result": asdict(run_rebuild(ctx))}
    if name == "reconcile":
        pg, ctx = _pgm()
        with pg.session() as s:
            q = select(Chunk.doc_version_id).distinct()
            if batch_id:
                q = q.join(DocVersion, DocVersion.doc_version_id == Chunk.doc_version_id).where(
                    DocVersion.batch_id == batch_id
                )
            dvids = list(s.scalars(q))
        return {"result": asdict(run_reconcile(ctx, dvids))}
    pg, ctx = _light() if name == "replay" else _worker()
    dvids = cli._indexed_dvids(pg, batch_id, effective_only=(name == "smoke"))
    if name == "replay":
        return {"result": asdict(run_replay(ctx, dvids))}
    if name == "smoke":
        return {"result": asdict(run_smoke(ctx, dvids))}
    raise ValueError(f"未知验证组件: {name}")


def batch_report(batch_id: str) -> dict[str, Any]:
    pg, ctx = _pgm()
    rep = build_report(ctx, batch_id)
    if rep["doc_count"] == 0:
        raise KeyError(batch_id)
    with pg.session() as s:
        ib = s.get(ImportBatch, batch_id)
        if ib is not None:
            ib.report = rep
    return rep


def search(
    query: str,
    topk: int = 10,
    include_superseded: bool = False,
    corpus: str | None = None,
) -> dict:
    pg, ctx = _worker()
    emb = ctx.embedding.embed([query])[0]
    corpus_type = {"internal": "P-INT", "external": "P-EXT"}.get(corpus or "", corpus)
    result = ctx.milvus.search(
        emb.dense,
        emb.sparse,
        topk=topk,
        include_superseded=include_superseded,
        corpus=corpus_type,
    )
    # E1 义务标注(复用 CLI 的 PG 回查,不动 Milvus schema):search 出义务条款标 [义务]
    obligation = cli._obligation_chunk_ids(pg, [h.get("chunk_id") for h in result.hits])
    hits = [{**h, "is_obligation": h.get("chunk_id") in obligation} for h in result.hits]
    return {
        "query": query,
        "retrieval_mode": result.retrieval_mode,
        "expr": result.expr,
        "hits": hits,
    }


def reset_uploads() -> None:
    if UPLOAD_ROOT.exists():
        shutil.rmtree(UPLOAD_ROOT)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
