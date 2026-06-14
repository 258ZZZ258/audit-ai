"""``demo`` CLI(typer)。环境编排 up/down + 接入到质检的链路:ingest / status / queue。

后续模块逐步接入:meta/search/verify/rebuild/reprocess/report。
"""

from __future__ import annotations

import subprocess
import sys
from collections import Counter
from pathlib import Path

import typer
from sqlalchemy import select
from ulid import ULID

from pipeline.config import load_config
from pipeline.index.milvus_io import MilvusIO
from pipeline.index.object_store import ObjectStore
from pipeline.index.pg_io import PgIO
from pipeline.index.pg_models import DocVersion, ReviewQueue
from pipeline.orchestrator import Orchestrator, Stage
from pipeline.queue import dispose
from pipeline.stage_base import StageContext
from pipeline.stages import s1_parse, s2_qc
from pipeline.stages.s0_register import register_batch
from pipeline.states import PipelineState

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
def _build_stages() -> dict[PipelineState, Stage]:
    """state → stage 纯函数(add-only,C 段加 s3/s4/s5)。s0 为 ingest 入口,非轮询 stage。

    REGISTERED→PARSING(s1.start 薄认领)→QC_PENDING(s1.run 解析)→STRUCTURING/QC_FAILED(s2.run)。
    过 QC 的件停在 STRUCTURING(C 段前无 s3 stage,该态不被轮询)。
    """
    return {
        PipelineState.REGISTERED: s1_parse.start,
        PipelineState.PARSING: s1_parse.run,
        PipelineState.QC_PENDING: s2_qc.run,
    }


def _context(cfg=None) -> tuple[PgIO, StageContext]:
    cfg = cfg or load_config()
    pg = PgIO.from_config(cfg)
    return pg, StageContext(config=cfg, object_store=ObjectStore.from_config(cfg), db=pg)


def _advance_one(pg: PgIO, ctx: StageContext, dvid: str, *, max_steps: int = 20) -> tuple[int, str]:
    """只推进本文档(逐步取自身当前态调对应 stage)直至无 stage 可推进;不触碰其他文档。"""
    orch = Orchestrator(pg, ctx, _build_stages())
    steps = 0
    while steps < max_steps:
        dv = pg.get(DocVersion, dvid)
        if dv is None or not orch.step(dv):  # 当前态无 stage → 停
            break
        steps += 1
    final = pg.get(DocVersion, dvid)
    return steps, (final.pipeline_status if final else "?")


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
    """S0 登记整批 → 跑 worker 推进至各自停态(QC_PENDING 前的链路)。"""
    cfg = load_config()
    pg, ctx = _context(cfg)
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
    pg, ctx = _context(cfg)
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


if __name__ == "__main__":
    app()
