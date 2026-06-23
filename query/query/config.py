"""查询智能体配置:读 ``config/settings.toml`` 的 ``[query]`` 段,返回类型化 ``QueryConfig``。

约定同 ``pipeline.config``:所有 ⚠ 可调值收口 config、禁硬编码;backend 选择等运行期值支持 env
覆盖。``config/`` 置 repo 根(非成员目录内,避免 flat 布局命名空间遮蔽,见 ``pipeline.config``)。
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

# query/query/config.py → parents[2] = <repo> → /config(与 pipeline.config 同源)
DEFAULT_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


class QueryConfig(BaseModel):
    """检索/生成/路由的 ⚠ 可调值。backend 默认 stub/none(零网络、无额外模型)。"""

    topk: int = 8                  # ⚠ 送生成的最终上下文条数(§5.5 top8)
    partition_topk: int = 25       # ⚠ 内规/外规各分区召回条数(§5.2 top25)
    sufficiency_min_hits: int = 1  # ⚠ 事项分区内充分判据最少命中(§8.1 务实版)
    attach_cases: bool = True      # ⚠ R1 依据答复尾挂相关案例卡(§6.3 附挂通道);可关
    attach_topk: int = 3           # ⚠ 附挂案例卡条数(§6.3 top3)
    llm_backend: Literal["stub", "gateway"] = "stub"   # QUERY_LLM_BACKEND 覆盖
    rerank_backend: Literal["none", "bge"] = "none"    # QUERY_RERANK_BACKEND 覆盖
    llm_model: str = "gpt-5.4-nano"  # ⚠ gateway 时模型名;env OPENAI_MODEL 可覆盖


def _apply_env(raw: dict) -> None:
    """对 backend / 模型名做 env 覆盖(就地修改 raw)。"""
    env = os.environ
    if "QUERY_LLM_BACKEND" in env:
        raw["llm_backend"] = env["QUERY_LLM_BACKEND"]
    if "QUERY_RERANK_BACKEND" in env:
        raw["rerank_backend"] = env["QUERY_RERANK_BACKEND"]
    if "OPENAI_MODEL" in env:
        raw["llm_model"] = env["OPENAI_MODEL"]


def load_query_config(config_dir: str | os.PathLike | None = None) -> QueryConfig:
    """读 settings.toml 的 ``[query]`` 段(缺段则全默认),应用 env 覆盖,返回 ``QueryConfig``。

    config_dir 优先级:显式参数 > 环境变量 QUERY_CONFIG_DIR > 默认 ``<repo>/config``。
    """
    cdir = Path(config_dir) if config_dir else Path(
        os.environ.get("QUERY_CONFIG_DIR", DEFAULT_CONFIG_DIR)
    )
    settings_raw = tomllib.loads((cdir / "settings.toml").read_text(encoding="utf-8"))
    raw = dict(settings_raw.get("query", {}))  # 缺 [query] 段 → 全默认
    _apply_env(raw)
    return QueryConfig(**raw)
