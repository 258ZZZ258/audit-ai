"""T2/T4(单元,零栈零网络):N3 问题分解 retrieve/decompose.py 纯函数 + Retriever fan-out。

T2 覆盖 SC1(拆分)/SC4(fail-safe)/SC5(max_sub)/SC8(不臆造);T4 覆盖 SC2(fan-out 并集)/SC3(no-op)。
复合问句拆子查询(§3.3),单跳/失败 → [原问];**不迭代**(§0.3 一次性);不产 clause_id(§7.1)。
"""

from __future__ import annotations

from query.retrieve.decompose import (
    DECOMPOSE_SYSTEM,
    build_decompose_user,
    decompose_subqueries,
    parse_subqueries,
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


_Q = "私募权益投顾同时管偏股和偏债是否违规"


# ── parse_subqueries 畸形守护 ──────────────────────────────────────────────
def test_parse_subqueries_variants():
    assert parse_subqueries({"subqueries": ["a", "b"]}) == ["a", "b"]
    assert parse_subqueries({"subqueries": ["a", "", "  ", 5, "b"]}) == ["a", "b"]  # 过滤空/非串
    assert parse_subqueries({"subqueries": "not a list"}) == []
    assert parse_subqueries({}) == []
    assert parse_subqueries("not a dict") == []


# ── decompose_subqueries:拆分 + 单跳直通 + fail-safe + max_sub(SC1/4/5)──────
def test_decompose_compound():
    llm = _FakeLLM({"subqueries": ["私募权益投顾管偏股是否违规", "私募权益投顾管偏债是否违规"]})
    subs = decompose_subqueries(_Q, llm)
    assert len(subs) == 2
    assert "偏股" in subs[0] and "偏债" in subs[1]
    assert llm.calls == 1


def test_decompose_single_returns_original_query():
    # LLM 只拆出 1 个(单跳问句)→ 返原问(直通,不用 LLM 改写的单个)
    assert decompose_subqueries(_Q, _FakeLLM({"subqueries": ["仅一个子查询"]})) == [_Q]


def test_decompose_llm_raises_returns_query():
    assert decompose_subqueries(_Q, _FakeLLM(raises=True)) == [_Q]  # 抛 → 单查询


def test_decompose_empty_returns_query():
    assert decompose_subqueries(_Q, _FakeLLM({"subqueries": []})) == [_Q]
    assert decompose_subqueries(_Q, _FakeLLM({})) == [_Q]


def test_decompose_max_sub_truncates():
    llm = _FakeLLM({"subqueries": ["a", "b", "c", "d", "e", "f"]})
    assert decompose_subqueries(_Q, llm, max_sub=3) == ["a", "b", "c"]  # 截断至 max_sub


# ── prompt 红线:只拆、不作答、不编造(§7.1)+ 不迭代(§0.3)────────────────
def test_decompose_system_prompt_no_fabrication():
    assert "复合" in DECOMPOSE_SYSTEM
    assert "不要回答" in DECOMPOSE_SYSTEM or "只拆" in DECOMPOSE_SYSTEM
    assert "编造" in DECOMPOSE_SYSTEM  # 禁编造制度名/条款号
    assert _Q in build_decompose_user(_Q)


# ── T4:Retriever fan-out 接缝(fake embed/milvus/decompose_llm,零栈)───────────
class _Emb:
    def __init__(self, dense, sparse) -> None:
        self.dense = dense
        self.sparse = sparse


class _FakeEmbed:
    def __init__(self) -> None:
        self.texts: list[str] = []

    def embed(self, texts):
        self.texts.extend(texts)
        return [_Emb(dense=[float(len(t))], sparse={1: 1.0}) for t in texts]


class _Res:
    retrieval_mode = "hybrid"

    def __init__(self, hits) -> None:
        self.hits = hits


class _FakeMilvus:
    def __init__(self) -> None:
        self.searches: list = []

    def search(self, dense, sparse, **kw):
        self.searches.append(kw)
        return _Res([])


def _retriever(decompose_llm=None, hyde_llm=None):
    from query.config import load_query_config
    from query.retrieve.hybrid import Retriever

    return Retriever(
        _FakeEmbed(), _FakeMilvus(), load_query_config(),
        hyde_llm=hyde_llm, decompose_llm=decompose_llm,
    )


def test_subqueries_for_noop_without_decompose_llm():
    r = _retriever(decompose_llm=None)
    assert r._subqueries_for(_Q) == [_Q]  # 关/stub → 单查询(byte 等价)


def test_subqueries_for_decomposes():
    r = _retriever(decompose_llm=_FakeLLM({"subqueries": ["q1", "q2"]}))
    assert r._subqueries_for(_Q) == ["q1", "q2"]


def test_retrieve_single_query_when_no_decompose(monkeypatch):
    r = _retriever(decompose_llm=None)
    calls = []
    monkeypatch.setattr(r, "_search_candidates", lambda q, **k: calls.append(q) or {})
    r.retrieve(_Q)
    assert calls == [_Q]  # _subqueries_for→[query],_search_candidates 调 1 次


def test_retrieve_fans_out_union(monkeypatch):
    from query.retrieve.hybrid import Candidate

    r = _retriever(decompose_llm=_FakeLLM({"subqueries": ["q1", "q2"]}))
    calls = []

    def fake_search(q, **k):
        calls.append(q)
        cid = "A" if q == "q1" else "B"  # 不同子查询命中不同 chunk
        return {cid: Candidate(cid, 1.0, "P-INT", "DV1", None, None, False, "hybrid")}

    monkeypatch.setattr(r, "_search_candidates", fake_search)
    out = r.retrieve(_Q)
    assert calls == ["q1", "q2"]                      # fan-out 两子查询
    assert {c.chunk_id for c in out} == {"A", "B"}    # 候选并集


def test_enumerate_cases_no_decompose():
    llm = _FakeLLM({"subqueries": ["q1", "q2"]})
    r = _retriever(decompose_llm=llm)
    r.retrieve_enumerate(_Q)
    r.retrieve_cases(_Q)
    assert llm.calls == 0  # 枚举/案例不 decompose(仅主 retrieve)


def test_build_decompose_llm_only_gateway_on_with_key(monkeypatch):
    import query.retrieve.hybrid as hyb
    from query.config import load_query_config

    monkeypatch.setattr("query.llm.make_llm_client", lambda cfg, *, model=None: ("sentinel", model))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")  # 有 key
    base = load_query_config()
    assert hyb._build_decompose_llm(base) is None  # stub(默认)→ 不建
    gw_on = base.model_copy(update={"llm_backend": "gateway", "decompose": True})
    assert hyb._build_decompose_llm(gw_on) == ("sentinel", gw_on.decompose_model or gw_on.llm_model)
    gw_off = base.model_copy(update={"llm_backend": "gateway", "decompose": False})
    assert hyb._build_decompose_llm(gw_off) is None  # 关 → 不建
    # gateway 但无 OPENAI_API_KEY → 不建(no-op 降级,SPEC「无 key→[query]」;QUERY-N3-OFFLINE-GATE)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert hyb._build_decompose_llm(gw_on) is None
