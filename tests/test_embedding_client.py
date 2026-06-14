"""EmbeddingClient 测试。

纯单测(工厂/桩/空输入)免依赖;真实 BGE-M3 embed 测试 gate 在 [embed] extra + 模型缓存,
不可用则 skip(对齐 [离线缓存] 验收约定)。
"""

import os

import pytest

from pipeline.config import load_config
from pipeline.index.embedding_client import (
    EmbeddingClient,
    EndpointClient,
    LocalBGEM3Client,
)


def test_from_config_local():
    client = EmbeddingClient.from_config(load_config())
    assert isinstance(client, LocalBGEM3Client)  # settings.toml 默认 mode=local


def test_empty_returns_empty():
    # 空输入不触发模型加载(无需 FlagEmbedding/模型)
    assert LocalBGEM3Client(load_config().embedding).embed([]) == []


def test_endpoint_stub_raises():
    cfg = load_config().embedding
    with pytest.raises(NotImplementedError):
        EndpointClient(cfg).embed(["x"])


@pytest.fixture(scope="session")
def bgem3():
    # 真模型测试显式 gate 在本地模型路径:测试绝不联网下载(避免慢/挂),模型须预先备好
    # (modelscope 拉取或 HF 缓存,见 README)。未设即秒 skip。
    if not os.environ.get("PIPELINE_EMBEDDING_MODEL"):
        pytest.skip("未设 PIPELINE_EMBEDDING_MODEL(本地 BGE-M3 目录);真模型测试跳过")
    try:
        import FlagEmbedding  # noqa: F401
    except Exception:
        pytest.skip("FlagEmbedding 未安装([embed] extra)")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")  # 本地目录加载,杜绝任何联网
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    client = EmbeddingClient.from_config(load_config())
    try:
        client.embed(["探测"])
    except Exception as e:
        pytest.skip(f"BGE-M3 加载失败: {e}")
    return client


def test_embed_dense_and_sparse(bgem3):
    embs = bgem3.embed(["第一条 为加强管理制定本办法。", "甲方应当及时提交单据。"])
    assert len(embs) == 2
    for e in embs:
        assert len(e.dense) == 1024  # BGE-M3 稠密维度
        assert all(isinstance(x, float) for x in e.dense)
        assert e.sparse and all(isinstance(v, float) for v in e.sparse.values())  # 非空 + 浮点权重


def test_embed_deterministic(bgem3):
    # 同文本两次 embed → dense 一致(嵌入确定性,服务 rebuild/对账)
    a = bgem3.embed(["第一条 测试内容。"])[0]
    b = bgem3.embed(["第一条 测试内容。"])[0]
    assert a.dense == b.dense
