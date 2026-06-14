"""配置加载:把所有 ⚠ 可调值收口到 ``config/`` 三文件,返回类型化 ``Settings``。

约定(SPEC 边界):所有 ⚠ 数值禁止硬编码,必须经此处从 config 读。
连接串、嵌入模式、密钥等运行期/敏感值支持 env 覆盖(见 ``_apply_env``)。
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

# config.py 位于 <repo>/src/pipeline/config.py → parents[2] = <repo>
DEFAULT_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


class DbConfig(BaseModel):
    dsn: str


class MilvusConfig(BaseModel):
    host: str
    port: int
    collection: str
    hnsw_m: int
    hnsw_ef_construction: int
    upsert_batch: int  # ⚠ 批量 upsert 条数


class EmbeddingConfig(BaseModel):
    mode: Literal["local", "endpoint"]
    model_name: str
    batch_size: int  # ⚠
    max_length: int  # ⚠
    retries: int  # ⚠ 指数退避次数
    cache_dir: str | None = None  # HF_HOME(env 注入,离线缓存)
    endpoint_base_url: str | None = None  # OPENAI_BASE_URL(env)
    endpoint_api_key: str | None = None  # OPENAI_API_KEY(env)


class ObjectStoreConfig(BaseModel):
    root: str


class TogglesConfig(BaseModel):
    l2_enabled: bool  # M1 默认 false(零 LLM)
    e1_enabled: bool


class AlignConfig(BaseModel):
    """页码文本对齐参数(规范渲染件 + 文本对齐,见 SPEC《页码锚点机制》)。"""

    header_band_pct: float  # ⚠ 顶部页眉带占页高比例
    footer_band_pct: float  # ⚠ 底部页脚带占页高比例
    fuzzy_threshold: int  # ⚠ rapidfuzz 兜底阈值(0-100)


class ParseConfig(BaseModel):
    scanned_char_per_page_max: int  # ⚠ <此值/页 判扫描件 → 隔离
    parse_timeout_sec: int  # ⚠ 单文档解析超时


class ChunkConfig(BaseModel):
    target_token_min: int  # ⚠
    target_token_max: int  # ⚠
    parent_block_token_max: int  # ⚠ 父块(节级)上限,仅 PG


class QcThresholds(BaseModel):
    """S2 七指标阈值 + 边缘带 ε(全部 ⚠)。"""

    clause_coverage_min: float  # 指标1 条款覆盖率
    clause_continuity_max_gap: int  # 指标2 条号连续性(允许缺口数)
    hierarchy_illegal_max: int  # 指标3 层级合法性(倒挂块数)
    page_anchor_complete_min: float  # 指标4 页码锚点完整率
    table_empty_max: float  # 指标5 空表占比上限
    text_garbled_max: float  # 指标6 非 CJK 乱码占比上限
    extraction_sufficiency_min: float  # 指标7 抽取充分性
    edge_band_epsilon: float  # 边缘通过带 ε


class ProfileConfig(BaseModel):
    sampling_rate: float  # 抽检率:M1 保留字段,不消费


class Settings(BaseModel):
    db: DbConfig
    milvus: MilvusConfig
    embedding: EmbeddingConfig
    object_store: ObjectStoreConfig
    toggles: TogglesConfig
    align: AlignConfig
    parse: ParseConfig
    chunk: ChunkConfig
    qc: QcThresholds
    profiles: dict[str, ProfileConfig]
    config_dir: Path


def _apply_env(raw: dict) -> None:
    """对连接串/嵌入模式/密钥等做 env 覆盖(就地修改 raw)。"""
    env = os.environ
    if "PIPELINE_DB_DSN" in env:
        raw["db"]["dsn"] = env["PIPELINE_DB_DSN"]
    if "PIPELINE_MILVUS_HOST" in env:
        raw["milvus"]["host"] = env["PIPELINE_MILVUS_HOST"]
    emb = raw["embedding"]
    if "PIPELINE_EMBEDDING_MODE" in env:
        emb["mode"] = env["PIPELINE_EMBEDDING_MODE"]
    if "PIPELINE_EMBEDDING_MODEL" in env:  # 指向本地模型目录(离线/镜像下载场景,如信创目标)
        emb["model_name"] = env["PIPELINE_EMBEDDING_MODEL"]
    if "OPENAI_BASE_URL" in env:
        emb["endpoint_base_url"] = env["OPENAI_BASE_URL"]
    if "OPENAI_API_KEY" in env:
        emb["endpoint_api_key"] = env["OPENAI_API_KEY"]
    if "HF_HOME" in env:
        emb["cache_dir"] = env["HF_HOME"]


def load_config(config_dir: str | os.PathLike | None = None) -> Settings:
    """读取 settings.toml + qc_thresholds.yaml + profiles.yaml,应用 env 覆盖,返回 Settings。

    config_dir 解析优先级:显式参数 > 环境变量 PIPELINE_CONFIG_DIR > 默认 <repo>/config。
    """
    cdir = Path(config_dir) if config_dir else Path(
        os.environ.get("PIPELINE_CONFIG_DIR", DEFAULT_CONFIG_DIR)
    )

    settings_raw = tomllib.loads((cdir / "settings.toml").read_text(encoding="utf-8"))
    qc_raw = yaml.safe_load((cdir / "qc_thresholds.yaml").read_text(encoding="utf-8"))
    profiles_raw = yaml.safe_load((cdir / "profiles.yaml").read_text(encoding="utf-8"))

    _apply_env(settings_raw)

    return Settings(
        db=DbConfig(**settings_raw["db"]),
        milvus=MilvusConfig(**settings_raw["milvus"]),
        embedding=EmbeddingConfig(**settings_raw["embedding"]),
        object_store=ObjectStoreConfig(**settings_raw["object_store"]),
        toggles=TogglesConfig(**settings_raw["toggles"]),
        align=AlignConfig(**settings_raw["align"]),
        parse=ParseConfig(**settings_raw["parse"]),
        chunk=ChunkConfig(**settings_raw["chunk"]),
        qc=QcThresholds(**qc_raw),
        profiles={k: ProfileConfig(**v) for k, v in profiles_raw.items()},
        config_dir=cdir,
    )
