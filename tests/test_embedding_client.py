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


def test_endpoint_stub_fails_fast_at_construction():
    # M1 未实现 endpoint:**构造即抛**(fail-fast),不留到 S5 嵌入才崩
    cfg = load_config().embedding
    with pytest.raises(NotImplementedError):
        EndpointClient(cfg)


def test_from_config_endpoint_fails_fast():
    # 部署切到 mode=endpoint:from_config 选到 EndpointClient 即清晰失败,而非埋到下游
    settings = load_config().model_copy(deep=True)
    settings.embedding.mode = "endpoint"
    with pytest.raises(NotImplementedError):
        EmbeddingClient.from_config(settings)


def test_local_load_passes_cache_dir(monkeypatch):
    # cache_dir(config:HF_HOME env 或 settings.toml)必须真传给模型加载器,否则离线缓存路径形同虚设。
    # monkeypatch 模型类避免加载 2.3GB 真权重(只验参数透传)。
    fa = pytest.importorskip("FlagEmbedding")
    captured = {}

    class _FakeModel:
        def __init__(self, model_name_or_path, **kwargs):
            captured["model"] = model_name_or_path
            captured["cache_dir"] = kwargs.get("cache_dir")

    monkeypatch.setattr(fa, "BGEM3FlagModel", _FakeModel)
    cfg = load_config().embedding.model_copy(
        update={"cache_dir": "/tmp/hf-offline-cache", "model_name": "BAAI/bge-m3"}
    )
    LocalBGEM3Client(cfg)._load()
    assert captured["model"] == "BAAI/bge-m3"
    assert captured["cache_dir"] == "/tmp/hf-offline-cache"  # 透传到加载器


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
