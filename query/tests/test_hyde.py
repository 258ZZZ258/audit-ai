"""T2/T4(单元,零栈零网络):N1 HyDE retrieve/hyde.py 纯函数 + Retriever._dense_for 接缝。

T2 覆盖 SC1(生成)/SC3(fail-safe)/SC7(不臆造);T4 覆盖 SC1/SC2(no-op)/SC3(回落)/SC6(仅主 retrieve)。
HyDE 只改 dense、绝不产出 clause_id(§7.1);LLM 失败 → None → 调用方回落原问 dense(绝不阻断)。
"""

from __future__ import annotations

from query.retrieve.hyde import (
    HYDE_SYSTEM,
    build_hyde_user,
    hyde_dense_text,
    parse_passage,
)


class _FakeLLM:
    """LLMClient 桩:返回固定 resp,或 raises=True 抛(验 fail-safe)。"""

    def __init__(self, resp: dict | None = None, *, raises: bool = False) -> None:
        self._resp = resp
        self._raises = raises
        self.calls = 0

    def chat_json(self, system: str, user: str) -> dict:
        self.calls += 1
        if self._raises:
            raise RuntimeError("gateway boom")
        return self._resp or {}


_Q = "二维码介绍开户违不违规"


# ── parse_passage 畸形守护 ─────────────────────────────────────────────────
def test_parse_passage_variants():
    assert parse_passage({"passage": "金融机构应当核实客户身份。"}) == "金融机构应当核实客户身份。"
    assert parse_passage({"passage": "  trim  "}) == "trim"
    assert parse_passage({"passage": ""}) is None
    assert parse_passage({"passage": 123}) is None
    assert parse_passage({}) is None
    assert parse_passage("not a dict") is None


# ── hyde_dense_text:生成 + fail-safe(SC1/SC3)─────────────────────────────
def test_hyde_dense_text_generates():
    llm = _FakeLLM({"passage": "经营机构不得违规招揽客户、不得居间介绍开户。"})
    out = hyde_dense_text(_Q, llm)
    assert out is not None
    assert out.startswith(_Q)                                  # 原问在前(一同送入 dense)
    assert "违规招揽客户" in out                                # 假设性法言并入
    assert llm.calls == 1


def test_hyde_dense_text_llm_raises_returns_none():
    assert hyde_dense_text(_Q, _FakeLLM(raises=True)) is None  # 抛 → None → 调用方回落原问


def test_hyde_dense_text_empty_returns_none():
    assert hyde_dense_text(_Q, _FakeLLM({"passage": "   "})) is None
    assert hyde_dense_text(_Q, _FakeLLM({})) is None


# ── prompt 红线:只写假设性法言、不作答、不编造(§7.1)──────────────────────
def test_hyde_system_prompt_no_fabrication():
    assert "假设" in HYDE_SYSTEM
    assert "不要回答" in HYDE_SYSTEM or "只写" in HYDE_SYSTEM
    assert "编造" in HYDE_SYSTEM  # 禁编造发文字号/条款号
    user = build_hyde_user(_Q)
    assert _Q in user


# ── T4:Retriever._dense_for 接缝 + hyde_llm 门控(fake embed/milvus,零栈)──────
class _Emb:
    def __init__(self, dense, sparse) -> None:
        self.dense = dense
        self.sparse = sparse


class _FakeEmbed:
    """记录 embed 的文本;dense 编码文本长度以便断言「embed 了哪段」。"""

    def __init__(self) -> None:
        self.texts: list[str] = []

    def embed(self, texts):
        self.texts.extend(texts)
        return [_Emb(dense=[float(len(t))], sparse={1: 1.0}) for t in texts]


class _FakeRes:
    retrieval_mode = "hybrid"
    hits: list = []


class _FakeMilvus:
    def __init__(self) -> None:
        self.searches: list = []

    def search(self, dense, sparse, **kw):
        self.searches.append({"dense": dense, "sparse": sparse, **kw})
        return _FakeRes()


def _retriever(hyde_llm=None):
    from query.config import load_query_config
    from query.retrieve.hybrid import Retriever

    return Retriever(_FakeEmbed(), _FakeMilvus(), load_query_config(), hyde_llm=hyde_llm)


def test_dense_for_noop_without_hyde_llm():
    r = _retriever(hyde_llm=None)
    emb = r._embed.embed([_Q])[0]
    r._embed.texts.clear()
    assert r._dense_for(_Q, emb) == emb.dense   # 原问 dense(byte 等价)
    assert r._embed.texts == []                  # 无额外 embed(无 HyDE)


def test_dense_for_hyde_embeds_query_plus_passage():
    r = _retriever(hyde_llm=_FakeLLM({"passage": "经营机构不得违规招揽客户。"}))
    emb = r._embed.embed([_Q])[0]
    r._embed.texts.clear()
    dense = r._dense_for(_Q, emb)
    assert r._embed.texts == [f"{_Q}\n经营机构不得违规招揽客户。"]  # embed「原问+法言」
    assert dense != emb.dense                                      # 用 HyDE dense


def test_dense_for_fallback_when_llm_raises():
    r = _retriever(hyde_llm=_FakeLLM(raises=True))
    emb = r._embed.embed([_Q])[0]
    r._embed.texts.clear()
    assert r._dense_for(_Q, emb) == emb.dense   # 回落原问 dense
    assert r._embed.texts == []                  # 失败 → 不额外 embed


def test_retrieve_uses_hyde_dense():
    r = _retriever(hyde_llm=_FakeLLM({"passage": "P"}))
    r.retrieve(_Q)
    # dense 走 HyDE(原问+法言),sparse 走原问;搜索拿到 HyDE dense
    assert r._embed.texts == [_Q, f"{_Q}\nP"]   # 原问(sparse)+ HyDE(dense)
    assert r._milvus.searches[0]["dense"] == [float(len(f"{_Q}\nP"))]


def test_enumerate_does_not_hyde():
    llm = _FakeLLM({"passage": "P"})
    r = _retriever(hyde_llm=llm)
    r.retrieve_enumerate(_Q)
    assert r._embed.texts == [_Q]   # 仅原问(无 HyDE 拼接)
    assert llm.calls == 0            # R4 枚举不触 HyDE(仅主 retrieve)


def test_cases_does_not_hyde():
    llm = _FakeLLM({"passage": "P"})
    r = _retriever(hyde_llm=llm)
    r.retrieve_cases(_Q)
    assert r._embed.texts == [_Q]   # 仅原问
    assert llm.calls == 0            # R3 案例不触 HyDE


def test_build_hyde_llm_only_gateway_on_with_key(monkeypatch):
    import query.retrieve.hybrid as hyb
    from query.config import load_query_config

    # maybe_make_llm_client 调 client 模块内的 make_llm_client → patch 内层
    monkeypatch.setattr(
        "query.llm.client.make_llm_client", lambda cfg, *, model=None: ("sentinel", model)
    )
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")  # 有 key
    base = load_query_config()
    assert hyb._build_hyde_llm(base) is None  # stub(默认)→ 不建
    gw_on = base.model_copy(update={"llm_backend": "gateway", "hyde": True})
    assert hyb._build_hyde_llm(gw_on) == ("sentinel", gw_on.hyde_model or gw_on.llm_model)
    gw_off = base.model_copy(update={"llm_backend": "gateway", "hyde": False})
    assert hyb._build_hyde_llm(gw_off) is None  # 关 → 不建
    # gateway 但无 OPENAI_API_KEY → 不建(no-op 降级,SPEC「无 key→None」;QUERY-N1-OFFLINE-GATE)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert hyb._build_hyde_llm(gw_on) is None
