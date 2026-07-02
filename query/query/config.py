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
# §5.4 词典扩展种子(锚 repo 根,同 config;consumed-when-present,缺 → 扩展为空)
DEFAULT_SCENARIO_TERMS = str(
    Path(__file__).resolve().parents[2] / "seeds" / "dict_scenario_terms.csv"
)


class QueryConfig(BaseModel):
    """检索/生成/路由的 ⚠ 可调值。backend 默认 stub/none(零网络、无额外模型)。"""

    topk: int = 8                  # ⚠ 送生成的最终上下文条数(§5.5 top8)
    partition_topk: int = 25       # ⚠ 内规/外规各分区召回条数(§5.2 top25)
    enumerate_partition_topk: int = 50  # ⚠ R4 枚举模式各分区召回条数(§6.4 高 k 不激进截断)
    enumerate_topk: int = 50       # ⚠ R4 枚举模式合并后列举上限(放大 topk;⚠ V0 标定)
    sufficiency_min_hits: int = 1  # ⚠ 事项分区内充分判据最少命中(§8.1 务实版)
    attach_cases: bool = True      # ⚠ R1 依据答复尾挂相关案例卡(§6.3 附挂通道);可关
    attach_topk: int = 3           # ⚠ 附挂案例卡条数(§6.3 top3)
    judge_constituent_llm: bool = False   # ⚠ R5 构成要件框定用 LLM 抽取(§6.5②);默认关=clause直呈
    judge_multimodel_review: bool = False  # ⚠ R5 §9.2 多模型复核;默认关=代码后检+形态保障
    llm_backend: Literal["stub", "gateway"] = "stub"   # QUERY_LLM_BACKEND 覆盖
    rerank_backend: Literal["none", "bge"] = "none"    # QUERY_RERANK_BACKEND 覆盖
    rerank_model: str = "BAAI/bge-reranker-v2-m3"  # ⚠ §5.5 bge 模型名/路径;QUERY_RERANK_MODEL 覆盖
    llm_model: str = "gpt-5.4-nano"  # ⚠ gateway 时主答模型名;env OPENAI_MODEL 可覆盖
    # ⚠ §9.2 忠实性复核模型(Kimi),与主答 llm_model 分离(§9.1);默认 kimi-2.5 为意图占位,
    # 真名待甲方网关注册表;env QUERY_REVIEW_MODEL(query 专属)/ OPENAI_REVIEW_MODEL 覆盖。
    review_model: str = "kimi-2.5"
    # §3.4 N0 多轮上下文归并:默认开(已决①,LLM 为主);env QUERY_MERGE_CONTEXT 覆盖。默认
    # llm_backend=stub → 走规则版确定性归并(零网络);仅 gateway 时建归并客户端走真 LLM。
    merge_context: bool = True
    # ⚠ §9.1 N0 归并模型(CP-007 轻量调用);None → 复用主答 llm_model;env QUERY_MERGE_MODEL 覆盖。
    merge_model: str | None = None
    # §3.1 N1 HyDE 查询改写(口语→假设性法言→dense):默认开(已决①,对齐设计 §3 节点链)。
    # 默认 llm_backend=stub → hyde_llm 不建 → _dense_for 返原问 dense(no-op、byte 等价);仅
    # gateway 时真 HyDE。on/off 终值待 §13 V0 第5组 A/B 实测(§15-⑦);env QUERY_HYDE 覆盖。
    hyde: bool = True
    # ⚠ §9.1 N1 HyDE 模型(CP-007 轻量调用);None → 复用主答 llm_model;env QUERY_HYDE_MODEL 覆盖。
    hyde_model: str | None = None
    # §3.3 N3 问题分解(复合问句拆子查询→并行检索再综合):默认开(已决②,对齐设计 §3 节点链)。
    # 默认 stub → decompose_llm 不建 → _subqueries_for 返 [query](单查询 no-op、byte 等价);仅
    # gateway 时真拆分,仅复合问句(LLM 拆 >1)才 fan-out。env QUERY_DECOMPOSE 覆盖。
    decompose: bool = True
    # ⚠ §9.1 N3 分解模型(CP-007 轻量调用);None → 复用主答 llm_model;env QUERY_DECOMPOSE_MODEL 覆盖。
    decompose_model: str | None = None
    decompose_max_sub: int = 4  # ⚠ V0 fan-out 子查询上限(封顶复合检索成本;§3.3)
    # §9.3 Langfuse 全链路观测:**默认关**(观测外发外部服务、守零网络;区别于 N0/N1/N3 默认开)。
    # 开 + LANGFUSE_* creds(env)→ LangfuseTracer;否则 NoopTracer(零网络)。env QUERY_OBSERVE 覆盖。
    observe: bool = False
    # §5.4 sparse 精确通道(默认关 → byte 等价;系数 ⚠ V0 标定)
    docnum_boost: bool = False  # ⚠ §5.4 发文字号/全名 sparse 提权;QUERY_DOCNUM_BOOST 覆盖
    docnum_boost_factor: float = 2.0  # ⚠ V0 发文字号 token 提权系数
    scenario_expand: bool = False  # ⚠ §5.4 dict 扩 sparse 命中面;QUERY_SCENARIO_EXPAND 覆盖
    scenario_expand_factor: float = 1.0  # ⚠ V0 法言词扩展系数
    scenario_terms_path: str = DEFAULT_SCENARIO_TERMS  # QUERY_SCENARIO_TERMS_PATH 覆盖
    # SPEC-API §8:首页推荐问题(config 驱动,settings.toml [query].suggestions 可覆盖;非硬编码)。
    suggestions: list[str] = [
        "客户适当性管理的监管要求有哪些?",
        "持续管理的留痕要求是什么?",
        "相关监管处罚案例有哪些?",
        "投诉处置制度依据有哪些?",
    ]
    upload_dir: str | None = None  # ⚠ 附件上传目录;None → 系统临时目录/audit-query-uploads
    max_upload_bytes: int = 50 * 1024 * 1024  # ⚠ 上传大小上限(50MB,SPEC-API §8.4)


def _apply_env(raw: dict) -> None:
    """对 backend / 模型名做 env 覆盖(就地修改 raw)。"""
    env = os.environ
    if "QUERY_LLM_BACKEND" in env:
        raw["llm_backend"] = env["QUERY_LLM_BACKEND"]
    if "QUERY_RERANK_BACKEND" in env:
        raw["rerank_backend"] = env["QUERY_RERANK_BACKEND"]
    if "QUERY_RERANK_MODEL" in env:
        raw["rerank_model"] = env["QUERY_RERANK_MODEL"]
    if "OPENAI_MODEL" in env:
        raw["llm_model"] = env["OPENAI_MODEL"]
    # 复核模型:OPENAI_REVIEW_MODEL(通用)先,QUERY_REVIEW_MODEL(query 专属)后 → 后者优先。
    if "OPENAI_REVIEW_MODEL" in env:
        raw["review_model"] = env["OPENAI_REVIEW_MODEL"]
    if "QUERY_REVIEW_MODEL" in env:
        raw["review_model"] = env["QUERY_REVIEW_MODEL"]
    if "QUERY_MERGE_CONTEXT" in env:
        raw["merge_context"] = env["QUERY_MERGE_CONTEXT"]  # "0"/"1" → pydantic bool 强转
    if "QUERY_MERGE_MODEL" in env:
        raw["merge_model"] = env["QUERY_MERGE_MODEL"]
    if "QUERY_HYDE" in env:
        raw["hyde"] = env["QUERY_HYDE"]  # "0"/"1" → pydantic bool 强转
    if "QUERY_HYDE_MODEL" in env:
        raw["hyde_model"] = env["QUERY_HYDE_MODEL"]
    if "QUERY_DECOMPOSE" in env:
        raw["decompose"] = env["QUERY_DECOMPOSE"]  # "0"/"1" → pydantic bool 强转
    if "QUERY_DECOMPOSE_MODEL" in env:
        raw["decompose_model"] = env["QUERY_DECOMPOSE_MODEL"]
    if "QUERY_OBSERVE" in env:
        raw["observe"] = env["QUERY_OBSERVE"]  # "0"/"1" → pydantic bool 强转
    if "QUERY_DOCNUM_BOOST" in env:
        raw["docnum_boost"] = env["QUERY_DOCNUM_BOOST"]
    if "QUERY_SCENARIO_EXPAND" in env:
        raw["scenario_expand"] = env["QUERY_SCENARIO_EXPAND"]
    if "QUERY_SCENARIO_TERMS_PATH" in env:
        raw["scenario_terms_path"] = env["QUERY_SCENARIO_TERMS_PATH"]


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
