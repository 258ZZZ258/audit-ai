"""``demo`` CLI(typer)。环境编排 up/down + 全链路:ingest / status / queue / meta / search。

C7 接入 ``search``(混合检索 + 四级引用)与 ``meta list/confirm``(META_REVIEW 人工闸,放行后推进至
INDEXED)。后续模块:verify/rebuild/reprocess/report。
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import typer
from sqlalchemy import select
from ulid import ULID

from pipeline.config import load_config
from pipeline.index.embedding_client import EmbeddingClient
from pipeline.index.milvus_io import MilvusIO
from pipeline.index.object_store import ObjectStore
from pipeline.index.pg_io import PgIO
from pipeline.index.pg_models import DocVersion, ImportBatch, RemediationRecord, ReviewQueue
from pipeline.orchestrator import Orchestrator, Stage
from pipeline.queue import dispose
from pipeline.stage_base import StageContext, StageResult
from pipeline.stages import finalize, s1_parse, s2_qc, s3_structure, s4_meta, s5_embed_index
from pipeline.stages.s0_register import register_batch
from pipeline.states import REPROCESS_RESET_FROM, PipelineState
from pipeline.verify.idempotency import check_idempotency
from pipeline.verify.report import build_report

#: 推进到此类终态(且带 supersedes)即自动版本切换(D1)。
_INDEXED_STATES = frozenset({PipelineState.INDEXED.value, PipelineState.DEGRADED_INDEXED.value})

app = typer.Typer(help="文档处理管线 · 本地 Demo(M1)", no_args_is_help=True)

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "compose.yaml"


def _compose(*args: str) -> None:
    subprocess.run(["docker", "compose", "-f", str(COMPOSE_FILE), *args], check=True)


def _migrate() -> None:
    """建库:alembic upgrade head(用当前解释器,cwd=repo 根)。"""
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=REPO_ROOT, check=True)


@app.command()
def up() -> None:
    """拉起 pg16 + milvus2.4,健康等待,建库(alembic upgrade head)。"""
    typer.echo("→ docker compose up(健康等待,首次需拉镜像 + Milvus ~90s 启动)…")
    _compose("up", "-d", "--wait")
    typer.echo("→ alembic upgrade head…")
    _migrate()
    cfg = load_config()
    n_iss, n_dom = PgIO.from_config(cfg).seed_dicts(REPO_ROOT / "seeds")
    typer.echo(f"→ seed 字典:issuers={n_iss} biz_domains={n_dom}")
    mio = MilvusIO(cfg)
    mio.connect()
    mio.create_collection()
    mio.disconnect()
    typer.echo(f"→ Milvus collection {cfg.milvus.collection} 就绪")
    pg = cfg.db.dsn.split("@")[-1]
    typer.echo(f"✓ demo up 完成。PG={pg} Milvus={cfg.milvus.host}:{cfg.milvus.port}")


@app.command()
def down(
    volumes: bool = typer.Option(False, "--volumes", "-v", help="同时删除数据卷(清空 PG/Milvus)"),
) -> None:
    """拆除栈(默认保留数据卷)。"""
    args = ["down"]
    if volumes:
        args.append("-v")
    _compose(*args)
    typer.echo("✓ demo down 完成" + ("(含数据卷)" if volumes else ""))


# ── 编排器组装根(composition root)──────────────────────────────
def _structuring(ctx: StageContext, doc_version_id: str) -> StageResult:
    """STRUCTURING 复合(在装配层组合,守 CLAUDE.md「stage 之间不得互相 import」约束):

    先 s3 切块(副作用写 chunks,其 StageResult 弃用)→ 再 s4 元数据交叉校验(决定 META_REVIEW
    + 冲突时 meta_confirm 队列)。s3/s4 仍互不依赖、各自可测;最终态由 s4 决定。
    """
    s3_structure.run(ctx, doc_version_id)
    return s4_meta.run(ctx, doc_version_id)


def _build_stages() -> dict[PipelineState, Stage]:
    """state → stage 纯函数(add-only,C 段续加 s5)。s0 为 ingest 入口,非轮询 stage。

    REGISTERED→PARSING(s1.start 薄认领)→QC_PENDING(s1.run 解析)→STRUCTURING/QC_FAILED(s2.run)
    →META_REVIEW(_structuring = s3 切块 + s4 元数据)。过 QC 的件切块 + 校验后停 META_REVIEW
    (人工等待态,不被轮询),经 CLI meta confirm 放行(C7)。
    """
    return {
        PipelineState.REGISTERED: s1_parse.start,
        PipelineState.PARSING: s1_parse.run,
        PipelineState.QC_PENDING: s2_qc.run,
        PipelineState.STRUCTURING: _structuring,
        PipelineState.EMBEDDING: s5_embed_index.embed,
        PipelineState.INDEXING: s5_embed_index.index,
    }


def _context(cfg=None) -> tuple[PgIO, StageContext]:
    """轻上下文(无 embedding/milvus):status / queue list/show 等不推进 worker 的命令用。"""
    cfg = cfg or load_config()
    pg = PgIO.from_config(cfg)
    return pg, StageContext(config=cfg, object_store=ObjectStore.from_config(cfg), db=pg)


def _worker_context(cfg=None) -> tuple[PgIO, StageContext]:
    """全上下文(含 embedding + 已连接 milvus):推进 META_REVIEW→EMBEDDING→INDEXED 的命令用。

    仅 C7 的 ``meta confirm`` 需要(它放行人工闸后跑到 s5);ingest 与 queue 处置至多到 META_REVIEW
    人工闸即停,用轻 ``_context`` 即可。
    """
    cfg = cfg or load_config()
    pg = PgIO.from_config(cfg)
    mio = MilvusIO(cfg)
    mio.connect()
    ctx = StageContext(
        config=cfg, object_store=ObjectStore.from_config(cfg), db=pg,
        embedding=EmbeddingClient.from_config(cfg), milvus=mio,
    )
    return pg, ctx


def _advance_one(pg: PgIO, ctx: StageContext, dvid: str, *, max_steps: int = 20) -> tuple[int, str]:
    """只推进本文档至无 stage 可推进,不触碰其他文档。

    处置已落库,推进尽力而为:某 stage 抛错(如缺 IR)则报告后停,不崩命令。
    """
    orch = Orchestrator(pg, ctx, _build_stages())
    steps = 0
    while steps < max_steps:
        dv = pg.get(DocVersion, dvid)
        if dv is None:
            break
        try:
            if not orch.step(dv):  # 当前态无 stage → 停
                break
        except Exception as e:  # 推进中某 stage 失败(如缺 IR):不崩命令,报告后停
            typer.echo(f"  推进在 {dv.pipeline_status} 中止: {e}")
            break
        steps += 1
    final = pg.get(DocVersion, dvid)
    final_state = final.pipeline_status if final else "?"
    # D1:推进到 INDEXED 且带 supersedes → 自动版本原子切换(旧版置 superseded)。
    # 仅 worker ctx(含 milvus)才可能到 INDEXED;轻 ctx 至多停 META_REVIEW,故 milvus 必非空。
    if (
        final is not None
        and final_state in _INDEXED_STATES
        and final.supersedes_version_id
        and ctx.milvus is not None
    ):
        result = finalize.run(ctx, dvid)
        if result.switched:
            typer.echo(f"  版本切换:旧版 {result.old_dvid} → superseded")
    return steps, final_state


def _print_status(docs: list[DocVersion]) -> None:
    counts = Counter(d.pipeline_status for d in docs)
    typer.echo("状态分布:" + "  ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    for d in docs:
        typer.echo(f"  {d.doc_version_id}  {d.pipeline_status:<16} {d.source_filename or ''}")


@app.command()
def ingest(
    directory: Path = typer.Argument(..., help="批次目录(含原件)"),
    manifest: Path | None = typer.Option(
        None, "--manifest", "-m", help="manifest.xlsx(默认 <dir>/manifest.xlsx)"
    ),
) -> None:
    """S0 登记整批 → 跑 worker 推进至各自停态(过 QC 件切块+元数据后停 META_REVIEW 待人工确认)。"""
    cfg = load_config()
    pg, ctx = _context(cfg)  # 至多推进到 META_REVIEW(人工闸),不触 s5,无需 embedding/milvus
    mpath = manifest or (directory / "manifest.xlsx")
    batch_id = str(ULID())
    report = register_batch(ctx, batch_id, directory, mpath)
    if not report.accepted:
        typer.echo(f"✗ 整批拒收:{report.reject_reason}")
        raise typer.Exit(1)
    counts = report.counts()
    typer.echo(f"S0 登记 batch={batch_id}:" + "  ".join(f"{k}={v}" for k, v in counts.items()))
    for w in report.warnings:
        typer.echo(f"  ⚠ {w}")
    steps = Orchestrator(pg, ctx, _build_stages()).run_until_idle()
    typer.echo(f"→ worker 推进 {steps} 步")
    with pg.session() as s:
        docs = list(s.scalars(select(DocVersion).where(DocVersion.batch_id == batch_id)))
    _print_status(docs)


@app.command()
def status(batch: str | None = typer.Argument(None, help="批次 id(省略=全部)")) -> None:
    """按状态分布 + 逐条列出文档。"""
    pg, _ = _context()
    with pg.session() as s:
        q = select(DocVersion)
        if batch:
            q = q.where(DocVersion.batch_id == batch)
        docs = list(s.scalars(q.order_by(DocVersion.batch_id)))
    if not docs:
        typer.echo("(无文档)")
        return
    _print_status(docs)


# ── 统一审核队列 ────────────────────────────────────────────────
queue_app = typer.Typer(help="统一审核队列(所有人工动作的唯一入口)", no_args_is_help=True)
app.add_typer(queue_app, name="queue")


@queue_app.command("list")
def queue_list(show_all: bool = typer.Option(False, "--all", help="含已关闭项")) -> None:
    """列出队列项(默认仅 open)。"""
    pg, _ = _context()
    with pg.session() as s:
        q = select(ReviewQueue)
        if not show_all:
            q = q.where(ReviewQueue.status == "open")
        rows = list(s.scalars(q.order_by(ReviewQueue.created_at)))
    if not rows:
        typer.echo("(队列为空)")
        return
    for r in rows:
        typer.echo(
            f"  {r.queue_id}  {r.queue_type:<11} {r.status:<7} "
            f"{r.doc_version_id}  {r.reason or ''}"
        )


def _print_evidence(queue_type: str, evidence: dict) -> None:
    if queue_type == "qc_fix" and evidence.get("failed"):
        typer.echo("失败指标:")
        for f in evidence["failed"]:
            typer.echo(
                f"  [{f.get('index')}] {f.get('name')}  "
                f"值={f.get('value')} 阈值={f.get('threshold')}"
            )
            ev = f.get("evidence") or {}
            if ev.get("hint"):
                typer.echo(f"      定位: {ev['hint']}")
            extra = {k: v for k, v in ev.items() if k != "hint" and v not in (None, "", [], {})}
            if extra:
                typer.echo(f"      证据: {extra}")
        if evidence.get("marginal"):
            typer.echo(f"边缘指标(仅标记): {evidence['marginal']}")
    elif evidence:
        typer.echo(f"证据: {evidence}")


@queue_app.command("show")
def queue_show(queue_id: str) -> None:
    """打印队列项详情:失败指标 + 定位证据 + IR 片段路径。"""
    cfg = load_config()
    pg, _ = _context(cfg)
    store = ObjectStore.from_config(cfg)
    with pg.session() as s:
        r = s.get(ReviewQueue, queue_id)
        if r is None:
            typer.echo(f"✗ 队列项不存在: {queue_id}")
            raise typer.Exit(1)
        dv = s.get(DocVersion, r.doc_version_id)
    typer.echo(f"queue_id    {r.queue_id}")
    line = f"queue_type  {r.queue_type}   status={r.status}"
    typer.echo(line + (f"  disposition={r.disposition}" if r.disposition else ""))
    typer.echo(
        f"doc_version {r.doc_version_id}  [{dv.pipeline_status if dv else '?'}]  "
        f"{(dv.source_filename if dv else '') or ''}"
    )
    typer.echo(f"reason      {r.reason or ''}")
    _print_evidence(r.queue_type, r.evidence or {})
    ir_key = store.ir_key(r.doc_version_id)
    suffix = "" if store.exists(ir_key) else "  (未生成)"
    typer.echo(f"IR 片段     {store.root / ir_key}{suffix}")


def _do_dispose(queue_id: str, disposition: str, operator: str) -> None:
    cfg = load_config()
    pg, ctx = _context(cfg)  # fix/degrade/release 至多推进到 META_REVIEW 人工闸,不触 s5
    try:
        outcome = dispose(pg, queue_id, disposition, operator=operator)
    except (KeyError, ValueError) as e:
        typer.echo(f"✗ 处置失败: {e}")
        raise typer.Exit(1) from e
    typer.echo(
        f"✓ {disposition}: {outcome.doc_version_id}  "
        f"{outcome.before_state} → {outcome.after_state}"
    )
    steps, final = _advance_one(pg, ctx, outcome.doc_version_id)  # 重入态自动推进本件
    if steps:
        typer.echo(f"  worker 推进 {steps} 步 → {final}")


_OPERATOR = typer.Option("cli", "--operator", "-u", help="处置人(写 pipeline_events.actor)")


@queue_app.command("fix")
def queue_fix(queue_id: str, operator: str = _OPERATOR) -> None:
    """人工修复 IR 后重入质检(→ QC_PENDING)。"""
    _do_dispose(queue_id, "fix", operator)


@queue_app.command("degrade")
def queue_degrade(queue_id: str, operator: str = _OPERATOR) -> None:
    """降级入库(→ DEGRADED_INDEXED)。"""
    _do_dispose(queue_id, "degrade", operator)


@queue_app.command("reject")
def queue_reject(queue_id: str, operator: str = _OPERATOR) -> None:
    """退回(→ REJECTED)。"""
    _do_dispose(queue_id, "reject", operator)


@queue_app.command("release")
def queue_release(queue_id: str, operator: str = _OPERATOR) -> None:
    """隔离裁决放行,重入解析(→ PARSING)。"""
    _do_dispose(queue_id, "release", operator)


# ── 检索(混合查 + 四级引用)────────────────────────────────────
_DEFAULT_TOPK = 10  # --topk 默认(CLI 入参,可覆盖)
_CORPUS_MAP = {"internal": "P-INT", "external": "P-EXT"}  # CLI 词 → Milvus corpus_type


def _wrap_title(t: str | None) -> str | None:
    if not t:
        return None
    return t if t.startswith("《") else f"《{t}》"


def _print_hit(rank: int, h: dict, dv: DocVersion | None) -> None:
    """渲染单条命中的四级引用:文档+文号 / 条款路径 / 页码 / 版本+状态。"""
    title = _wrap_title(dv.title if dv else None) or h["doc_version_id"]
    doc_number = (dv.doc_number if dv else None) or ""
    corpus_type = h.get("corpus_type") or ""
    version_status = (dv.version_status if dv else None) or "?"
    page = h.get("page_start")  # s5 未对齐写 0(INT64 不收 None)
    chunk_status = h.get("status") or "?"

    typer.echo("")
    typer.echo(f"#{rank}  score {h['score']:.4f}")
    doc_line = f"  文档  {title}"
    if doc_number:
        doc_line += f" {doc_number}"
    if corpus_type:
        doc_line += f" ({corpus_type})"
    typer.echo(doc_line)
    typer.echo(f"  条款  {h.get('clause_path') or '(根)'}")
    typer.echo(f"  页码  第 {page} 页" if page else "  页码  (未对齐)")
    status_line = f"  状态  {chunk_status}   version={version_status}"
    if h.get("degraded"):
        status_line += "  [degraded]"
    typer.echo(status_line)
    typer.echo(f"  ref   chunk={h['chunk_id'][:8]}..  dvid={h['doc_version_id'][:8]}..")


def _print_search(pg: PgIO, query: str, result) -> None:
    typer.echo(f'检索: "{query}"  ({result.retrieval_mode}, hits={len(result.hits)})')
    if not result.hits:
        typer.echo("(无命中)")
        return
    dvids = {h["doc_version_id"] for h in result.hits}  # 回 PG 批量补四级引用元数据
    with pg.session() as s:
        docs = {
            d.doc_version_id: d
            for d in s.scalars(select(DocVersion).where(DocVersion.doc_version_id.in_(dvids)))
        }
    for rank, h in enumerate(result.hits, 1):
        _print_hit(rank, h, docs.get(h["doc_version_id"]))


@app.command()
def search(
    query: str = typer.Argument(..., help="检索词"),
    include_superseded: bool = typer.Option(
        False, "--include-superseded", help="含已替代旧版 superseded(staging 仍不可见)"
    ),
    corpus: str | None = typer.Option(
        None, "--corpus", help="internal(内规 P-INT)| external(外规 P-EXT)"
    ),
    topk: int = typer.Option(_DEFAULT_TOPK, "--topk", "-k", help="返回条数"),
) -> None:
    """混合检索 audit_corpus(dense+sparse),输出四级引用。

    默认仅 effective(staging/superseded 不可见);hybrid 受阻或 sparse 空时退化 dense-only。
    """
    corpus_type = None
    if corpus is not None:
        corpus_type = _CORPUS_MAP.get(corpus)
        if corpus_type is None:
            typer.echo(f"✗ --corpus 仅支持 internal|external,收到: {corpus}")
            raise typer.Exit(1)
    pg, ctx = _worker_context()  # 需 embedding(编码 query)+ milvus(检索)
    emb = ctx.embedding.embed([query])[0]
    result = ctx.milvus.search(
        emb.dense, emb.sparse, topk=topk,
        include_superseded=include_superseded, corpus=corpus_type,
    )
    _print_search(pg, query, result)


# ── META_REVIEW 元数据确认闸 ────────────────────────────────────
meta_app = typer.Typer(help="META_REVIEW 元数据确认闸(meta_confirm 队列)", no_args_is_help=True)
app.add_typer(meta_app, name="meta")


@meta_app.command("list")
def meta_list(show_all: bool = typer.Option(False, "--all", help="含已关闭项")) -> None:
    """列 meta_confirm 队列项(默认仅 open);冲突件高亮 conflicts。"""
    pg, _ = _context()
    with pg.session() as s:
        q = select(ReviewQueue).where(ReviewQueue.queue_type == "meta_confirm")
        if not show_all:
            q = q.where(ReviewQueue.status == "open")
        rows = list(s.scalars(q.order_by(ReviewQueue.created_at)))
        docs = {
            d.doc_version_id: d
            for d in s.scalars(
                select(DocVersion).where(
                    DocVersion.doc_version_id.in_({r.doc_version_id for r in rows})
                )
            )
        }
    if not rows:
        typer.echo("(无待确认元数据)")
        return
    for r in rows:
        conflicts = (r.evidence or {}).get("conflicts") or []
        flag = f"⚠冲突×{len(conflicts)}" if conflicts else "无冲突"
        dv = docs.get(r.doc_version_id)
        typer.echo(
            f"  {r.queue_id}  {r.status:<7} {flag:<9} {r.doc_version_id}  "
            f"{(dv.title if dv else '') or ''}"
        )
        for c in conflicts:
            typer.echo(
                f"      {c.get('field')}: manifest「{c.get('manifest')}」 "
                f"vs L1「{c.get('extracted')}」"
            )


def _open_meta_confirms(pg: PgIO, dvid: str) -> list[str]:
    with pg.session() as s:
        return [
            r.queue_id
            for r in s.scalars(
                select(ReviewQueue)
                .where(ReviewQueue.doc_version_id == dvid)
                .where(ReviewQueue.queue_type == "meta_confirm")
                .where(ReviewQueue.status == "open")
                .order_by(ReviewQueue.created_at)
            )
        ]


def _close_extra_meta(pg: PgIO, queue_id: str, operator: str) -> None:
    """关联 meta_confirm 行随同 doc 放行而关单(不再迁移;doc 已被首行迁移出 META_REVIEW)。"""
    with pg.session() as s:
        q = s.get(ReviewQueue, queue_id)
        if q is None or q.status != "open":
            return
        s.add(
            RemediationRecord(
                doc_version_id=q.doc_version_id, queue_id=queue_id, disposition="approve",
                operator=operator, reason="随同 doc 放行,关联 meta_confirm 一并关单",
            )
        )
        q.status, q.disposition, q.operator = "closed", "approve", operator
        q.processed_at = datetime.now(UTC)


def _approve_doc(pg: PgIO, ctx: StageContext, dvid: str, operator: str) -> None:
    """doc-centric 放行:首条 meta_confirm 走 approve(迁移 META_REVIEW→EMBEDDING),该 doc 其余
    open meta_confirm(merge/split 件有 s0+s4 两条)随之关单,再推进本件至 INDEXED。
    """
    qids = _open_meta_confirms(pg, dvid)
    if not qids:
        typer.echo(f"  (doc {dvid} 无 open meta_confirm,跳过)")
        return
    try:
        outcome = dispose(pg, qids[0], "approve", operator=operator)  # 迁移 + 关首行 + remediation
    except (KeyError, ValueError) as e:
        typer.echo(f"✗ 放行失败 {dvid}: {e}")
        return
    for qid in qids[1:]:  # 关联行(同 doc 其余 meta_confirm)
        _close_extra_meta(pg, qid, operator)
    extra = f"(+{len(qids) - 1} 关联项)" if len(qids) > 1 else ""
    typer.echo(f"✓ approve: {dvid}  {outcome.before_state} → {outcome.after_state}{extra}")
    steps, final = _advance_one(pg, ctx, dvid)  # approve→EMBEDDING→…→INDEXED
    if steps:
        typer.echo(f"  worker 推进 {steps} 步 → {final}")


@meta_app.command("confirm")
def meta_confirm(
    queue_id: str | None = typer.Argument(None, help="队列项 id(与 --batch 二选一)"),
    batch: str | None = typer.Option(None, "--batch", help="放行整批所有 open meta_confirm"),
    operator: str = _OPERATOR,
) -> None:
    """放行 META_REVIEW(approve 处置)→ 推进至 INDEXED。单条 queue_id 或 --batch 整批。

    doc-centric:一件即便有多条 open meta_confirm(merge/split 的 s0+s4)也只放行一次、全部关单。
    """
    if (queue_id is None) == (batch is None):
        typer.echo("✗ 需且仅需指定 queue_id 或 --batch 之一")
        raise typer.Exit(1)
    pg, ctx = _worker_context()  # approve 后跑 s5(嵌入+索引),需 embedding + milvus
    if batch is not None:
        with pg.session() as s:
            rows = list(
                s.scalars(
                    select(ReviewQueue)
                    .join(DocVersion, DocVersion.doc_version_id == ReviewQueue.doc_version_id)
                    .where(ReviewQueue.queue_type == "meta_confirm")
                    .where(ReviewQueue.status == "open")
                    .where(DocVersion.batch_id == batch)
                    .order_by(ReviewQueue.created_at)
                )
            )
        dvids = list(dict.fromkeys(r.doc_version_id for r in rows))  # 去重保序(一件多行只放行一次)
        if not dvids:
            typer.echo(f"(批次 {batch} 无 open meta_confirm 项)")
            return
        typer.echo(f"→ 整批放行 {len(dvids)} 件")
    else:
        with pg.session() as s:
            q = s.get(ReviewQueue, queue_id)
            if q is None:
                typer.echo(f"✗ 队列项不存在: {queue_id}")
                raise typer.Exit(1)
            if q.queue_type != "meta_confirm":
                typer.echo(f"✗ {queue_id} 非 meta_confirm 项(queue_type={q.queue_type})")
                raise typer.Exit(1)
            dvids = [q.doc_version_id]
    for dvid in dvids:
        _approve_doc(pg, ctx, dvid, operator)


# ── reprocess(全量重跑 + 清孤儿)────────────────────────────────
@app.command()
def reprocess(
    doc_version_id: str = typer.Argument(..., help="待重跑的 doc_version_id"),
    operator: str = _OPERATOR,
) -> None:
    """全量重跑单件:清孤儿(Milvus 投影)→ 重置 REGISTERED → 重跑至 INDEXED(自动重确认)。

    确定性 chunk_id 使重跑安全(同 id 覆盖)。仅终态/失败态可重跑(REPROCESS_RESET_FROM)。
    """
    pg, ctx = _worker_context()  # 重跑跑完 s5,需 embedding + milvus
    dv = pg.get(DocVersion, doc_version_id)
    if dv is None:
        typer.echo(f"✗ 文档不存在: {doc_version_id}")
        raise typer.Exit(1)
    if PipelineState(dv.pipeline_status) not in REPROCESS_RESET_FROM:
        typer.echo(f"✗ 当前态 {dv.pipeline_status} 不可 reprocess(仅终态/失败态可)")
        raise typer.Exit(1)

    ctx.milvus.delete(doc_version_id)  # 清孤儿:删旧投影(PG chunk 由 s3 replace_chunks 重跑覆盖)
    ctx.milvus.flush()
    pg.transition(
        doc_version_id, PipelineState.REGISTERED, actor=operator, detail={"reprocess": True}
    )
    typer.echo(f"→ reprocess {doc_version_id}:已重置 REGISTERED + 清 Milvus 投影")
    steps, final = _advance_one(pg, ctx, doc_version_id)  # → META_REVIEW(人工闸停)
    if final == PipelineState.META_REVIEW.value:
        _approve_doc(pg, ctx, doc_version_id, operator)  # 自动重确认 → INDEXED(+finalize)
        final = pg.get(DocVersion, doc_version_id).pipeline_status
    typer.echo(f"✓ reprocess 完成 → {final}")


# ── verify(M1:idempotency;smoke/replay/reconcile 属 M2,D5 占位)──
verify_app = typer.Typer(help="验证组件(M1 仅 idempotency=V5)", no_args_is_help=True)
app.add_typer(verify_app, name="verify")


@verify_app.command("idempotency")
def verify_idempotency(
    directory: Path = typer.Argument(..., help="已 ingest 过的批次目录"),
    manifest: Path | None = typer.Option(None, "--manifest", "-m", help="默认 <dir>/manifest.xlsx"),
) -> None:
    """V5:对已入库批次重复 ingest,断言 chunk_id 集合 + Milvus 实体数不变、第二次有去重留痕。"""
    pg, ctx = _worker_context()  # 需 milvus(count);不重嵌入,模型不加载
    report = check_idempotency(ctx, directory, manifest or (directory / "manifest.xlsx"))
    for line in report.lines:
        typer.echo(line)
    typer.echo("幂等验证:" + ("通过 ✓" if report.passed else "未通过 ✗"))
    if not report.passed:
        raise typer.Exit(1)


# ── M2 占位(SPEC:禁伪造断言;M1 打印「非 M1 范围」+ 非零退出)──
def _not_m1(name: str) -> None:
    typer.echo(f"✗ {name} 属 M2,非 M1 范围(未实现;按 SPEC 禁止伪造断言)。")
    raise typer.Exit(2)


@verify_app.command("smoke")
def verify_smoke() -> None:
    """[M2 占位] T2 冒烟检索——非 M1 范围,非零退出。"""
    _not_m1("verify smoke(T2 冒烟)")


@verify_app.command("replay")
def verify_replay() -> None:
    """[M2 占位] T4 锚点回放——非 M1 范围,非零退出。"""
    _not_m1("verify replay(T4 锚点回放)")


@verify_app.command("reconcile")
def verify_reconcile() -> None:
    """[M2 占位] PG/Milvus 对账——非 M1 范围,非零退出。"""
    _not_m1("verify reconcile(PG/Milvus 对账)")


@app.command()
def rebuild() -> None:
    """[M2 占位] 删集合 + 从 PG/冷备重建——非 M1 范围,非零退出。"""
    _not_m1("rebuild(Milvus 重建)")


# ── report(批次指标快照)──────────────────────────────────────
def _pct(x: float | None) -> str:
    return f"{x:.1%}" if x is not None else "—"


@app.command()
def report(batch: str = typer.Argument(..., help="批次 id")) -> None:
    """批次指标:解析成功率 / QC 一次通过率 / 状态计数 / 锚点填充率 / retrieval_mode。

    输出控制台摘要 + JSON,并把快照落库到 import_batches.report。
    """
    pg, ctx = _worker_context()  # 需 milvus 探 retrieval_mode
    rep = build_report(ctx, batch)
    if rep["doc_count"] == 0:
        typer.echo(f"✗ 批次无文档: {batch}")
        raise typer.Exit(1)
    with pg.session() as s:  # 持久化快照到 import_batches.report
        ib = s.get(ImportBatch, batch)
        if ib is not None:
            ib.report = rep
    typer.echo(f"批次 {batch}  文档 {rep['doc_count']}  块 {rep['chunk_count']}")
    typer.echo("状态分布:" + "  ".join(f"{k}={v}" for k, v in rep["status_counts"].items()))
    typer.echo(
        f"解析成功率 {_pct(rep['parse_success_rate'])}  "
        f"QC 一次通过率 {_pct(rep['qc_first_pass_rate'])}  "
        f"锚点填充率 {_pct(rep['anchor_fill_rate'])}"
    )
    typer.echo(f"retrieval_mode {rep['retrieval_mode']}")
    typer.echo(json.dumps(rep, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    app()
