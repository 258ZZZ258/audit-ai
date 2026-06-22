"""T1 冒烟:query 包可导入 + 依赖 DAG 无环(pipeline import 期不反依赖 query)。"""

from __future__ import annotations

import subprocess
import sys


def test_query_imports():
    import query  # noqa: F401


def test_dag_acyclic_pipeline_not_import_query():
    """子进程 import pipeline 后 sys.modules 不应含 query —— 守 query → pipeline 单向。"""
    code = "import pipeline, sys; assert 'query' not in sys.modules"
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, f"pipeline 反依赖 query 或 import 失败:\n{r.stderr}"
