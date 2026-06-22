"""T14:CLI thin shell——`query route`(免栈)+ help 列命令。`ask` 连栈见 graph 集成。"""

from __future__ import annotations

from typer.testing import CliRunner

from query.cli import app

runner = CliRunner()


def test_route_command_evidence():
    r = runner.invoke(app, ["route", "费用报销三个月的规定在哪里"])
    assert r.exit_code == 0
    assert "route_type=evidence" in r.stdout


def test_route_command_off_domain_refuse():
    r = runner.invoke(app, ["route", "今天天气怎么样"])
    assert r.exit_code == 0
    assert "route_type=refuse" in r.stdout


def test_help_lists_commands():
    r = runner.invoke(app, ["--help"])
    assert r.exit_code == 0
    assert "ask" in r.stdout and "route" in r.stdout
