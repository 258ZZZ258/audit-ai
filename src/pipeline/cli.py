"""``demo`` CLI(typer)。M1 起步:环境编排 up/down。

后续模块逐步接入:ingest/status/queue/meta/search/verify/rebuild/reprocess/report。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import typer

from pipeline.config import load_config
from pipeline.index.milvus_io import MilvusIO
from pipeline.index.pg_io import PgIO

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


if __name__ == "__main__":
    app()
