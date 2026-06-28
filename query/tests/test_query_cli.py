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


# ── ask --history-json(N0 多轮入口;monkeypatch from_config 免栈)──────────────
def _fake_agent(captured: dict):
    from query.contract import QueryResult, RouteType

    class _A:
        def ask(self, query, history=None):
            captured["query"] = query
            captured["history"] = history
            return QueryResult(RouteType.CLARIFY)

    return _A()


def _patch_from_config(monkeypatch, captured):
    import query.graph as gmod

    monkeypatch.setattr(
        gmod.QueryAgent, "from_config", classmethod(lambda cls: _fake_agent(captured))
    )


def test_ask_history_json_parsed(monkeypatch):
    captured: dict = {}
    _patch_from_config(monkeypatch, captured)
    hist = (
        '[{"role":"user","content":"合同管理办法什么时候改的"},'
        '{"role":"assistant","content":"现行还是历史?","route_type":"clarify"}]'
    )
    r = runner.invoke(app, ["ask", "现行版本", "--history-json", hist])
    assert r.exit_code == 0
    assert captured["query"] == "现行版本"
    assert isinstance(captured["history"], list) and len(captured["history"]) == 2
    assert captured["history"][0]["content"] == "合同管理办法什么时候改的"


def test_ask_no_history_single_turn(monkeypatch):
    captured: dict = {}
    _patch_from_config(monkeypatch, captured)
    r = runner.invoke(app, ["ask", "费用报销规定在哪"])
    assert r.exit_code == 0
    assert captured["history"] is None  # 不传 → 单轮(graph 内 history=[])


def test_ask_malformed_history_json_errors(monkeypatch):
    captured: dict = {}
    _patch_from_config(monkeypatch, captured)
    r = runner.invoke(app, ["ask", "q", "--history-json", "{not valid json"])
    assert r.exit_code != 0          # 友好报错,非栈崩
    assert "query" not in captured   # 畸形 → 未触达 ask


def test_ask_history_json_not_array_errors(monkeypatch):
    captured: dict = {}
    _patch_from_config(monkeypatch, captured)
    r = runner.invoke(app, ["ask", "q", "--history-json", '{"role":"user"}'])
    assert r.exit_code != 0          # 须为 JSON 数组
    assert "query" not in captured
