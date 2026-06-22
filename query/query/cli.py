"""``query`` CLI(thin shell over QueryAgent)。``query ask`` 端到端;``query route`` 仅路由判定。

``ask`` 连真栈(PG+Milvus+本地 BGE-M3,需先 ``demo up``);LLM 默认 stub(零网络),gateway 经
``QUERY_LLM_BACKEND``。``route`` 免栈(只跑分类+路由)。域逻辑在 query.graph,本层只做参数与打印。
"""

from __future__ import annotations

import typer

app = typer.Typer(
    help="制度查询智能体 · MVP(R1 依据查询 + 覆盖感知拒答 + 八路路由骨架)",
    no_args_is_help=True,
)


@app.command()
def ask(
    query: str = typer.Argument(..., help="查询问句"),
    indent: bool = typer.Option(False, "--indent", help="缩进打印 JSON"),
) -> None:
    """R1 端到端:检索 → 引用约束生成 → 四级引用,输出 §10 契约 JSON(连真栈)。"""
    from query.graph import QueryAgent

    res = QueryAgent.from_config().ask(query)
    typer.echo(res.to_json(indent=2 if indent else None))


@app.command()
def route(query: str = typer.Argument(..., help="查询问句")) -> None:
    """仅打印八路路由判定(调试),不触发检索。"""
    from query.understand.classify import classify
    from query.understand.router import route as _route

    scene = classify(query)
    d = _route(query, scene)
    typer.echo(
        f"route_type={d.route_type.value} confidence={d.confidence} "
        f"scene={scene.scene_type.value} reason={d.reason}"
    )
