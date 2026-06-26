"""§5.4-T1(单元):查询层 sparse 精确增强。零栈零模型(fake embed)。

detect_doc_numbers(发文字号 + 《全名》, 不误命中) · load_scenario_terms(CSV→dict, 缺/空→{}) ·
augment_sparse(命中加权并入 / 无命中返 base_sparse 同一性 / 只动 sparse / docnum·expand 独立)。
"""

from __future__ import annotations

from types import SimpleNamespace

from query.retrieve.sparse_boost import (
    augment_sparse,
    detect_doc_numbers,
    load_scenario_terms,
)


# ── detect_doc_numbers ───────────────────────────────────────────────
def test_detect_docnum_basic():
    assert detect_doc_numbers("银保监发〔2021〕5号 的处罚标准") == ["银保监发〔2021〕5号"]


def test_detect_docnum_variants():
    assert detect_doc_numbers("证监发〔2020〕第53号") == ["证监发〔2020〕第53号"]
    assert detect_doc_numbers("财会〔2017〕22号") == ["财会〔2017〕22号"]


def test_detect_docnum_fullwidth():
    # 全角数字 + 全角括号 → to_halfwidth 归一后命中
    assert detect_doc_numbers("（２０２３）５号") == ["(2023)5号"]


def test_detect_title():
    assert detect_doc_numbers("《证券公司监督管理条例》怎么说") == ["《证券公司监督管理条例》"]


def test_detect_no_false_positive():
    assert detect_doc_numbers("这个制度的处罚标准是什么") == []
    assert detect_doc_numbers("我有2021个问题要问") == []  # 纯数字(无括号+号)不误命中


def test_detect_docnum_strips_query_prefix():
    # QUERY-SPARSE-DOCNUM-SPAN:裁掉问句/连接词前缀,只留机关代字+核心(不把"请问/根据"一起提权)
    assert detect_doc_numbers("请问银保监发〔2021〕5号是什么") == ["银保监发〔2021〕5号"]
    assert detect_doc_numbers("根据财会〔2017〕22号的规定") == ["财会〔2017〕22号"]
    assert detect_doc_numbers("请问〔2023〕5号") == ["〔2023〕5号"]  # 前缀 + 裸文号


# ── load_scenario_terms ──────────────────────────────────────────────
def test_load_scenario_terms(tmp_path):
    p = tmp_path / "d.csv"
    p.write_text(
        "oral_term,legal_terms\n代客理财,全权委托|受托理财\n见底到顶,对买卖时机的具体建议\n",
        encoding="utf-8",
    )
    d = load_scenario_terms(p)
    assert d["代客理财"] == ["全权委托", "受托理财"]
    assert d["见底到顶"] == ["对买卖时机的具体建议"]


def test_load_scenario_terms_missing(tmp_path):
    assert load_scenario_terms(tmp_path / "nope.csv") == {}


def test_load_scenario_terms_empty(tmp_path):
    p = tmp_path / "empty.csv"
    p.write_text("oral_term,legal_terms\n", encoding="utf-8")  # 仅表头
    assert load_scenario_terms(p) == {}


# ── augment_sparse(fake embed)────────────────────────────────────────
class _FakeEmbed:
    """按文本返预设 sparse(token_id→权重);记录调用。"""

    def __init__(self, table):
        self._table = table
        self.calls: list[list[str]] = []

    def embed(self, texts):
        self.calls.append(list(texts))
        return [SimpleNamespace(dense=[0.0], sparse=dict(self._table.get(t, {}))) for t in texts]


def test_augment_noop_both_off():
    base = {"x": 1.0}
    emb = _FakeEmbed({})
    out = augment_sparse("银保监发〔2021〕5号", base, embed=emb)  # 双关默认关
    assert out is base  # 同一性 → byte 等价
    assert emb.calls == []  # 无 embed 调用


def test_augment_noop_no_match():
    base = {"x": 1.0}
    emb = _FakeEmbed({})
    out = augment_sparse(
        "普通问句没有编号", base, embed=emb,
        docnum_on=True, expand_on=True, scenario_terms={"代客理财": ["受托理财"]},
    )
    assert out is base  # 开但无命中 → 仍同一性


def test_augment_docnum_boost():
    base = {"x": 1.0}
    span = "银保监发〔2021〕5号"
    emb = _FakeEmbed({span: {"tok_a": 0.5, "x": 0.2}})
    out = augment_sparse(f"{span} 的处罚标准", base, embed=emb, docnum_on=True, docnum_factor=2.0)
    assert out is not base  # 命中 → 新 dict
    assert out["tok_a"] == 2.0 * 0.5  # 新 token 按 factor 注入
    assert out["x"] == 1.0 + 2.0 * 0.2  # 既有 token 叠加
    assert base == {"x": 1.0}  # base 不被改(纯)


def test_augment_scenario_expand():
    base = {"x": 1.0}
    emb = _FakeEmbed({"受托理财": {"tok_b": 0.4}})
    out = augment_sparse(
        "代客理财违规吗", base, embed=emb,
        expand_on=True, expand_factor=1.0, scenario_terms={"代客理财": ["受托理财"]},
    )
    assert out["tok_b"] == 0.4  # 法言词 token 注入(扩命中面)


def test_augment_docnum_only_skips_dict():
    # docnum_on 单开(expand_on 关)→ 不读 dict;无发文字号 → 无命中
    base = {"x": 1.0}
    emb = _FakeEmbed({"受托理财": {"tok_b": 0.4}})
    out = augment_sparse(
        "代客理财违规吗", base, embed=emb,
        docnum_on=True, scenario_terms={"代客理财": ["受托理财"]},
    )
    assert out is base


def _ip(a, b):
    """稀疏内积(共享 token 权重乘积和)= sparse 通道的打分量。"""
    return sum(w * b[t] for t, w in a.items() if t in b)


def test_augment_docnum_strictly_raises_target_ip():
    # 机制非无效(STRICT,确定性):提权**严格增大** query 与"含发文字号 chunk"的 sparse 内积。
    # (检索 rank 改善是大语料 / §15 V0 性质;§5.1 hybrid 小语料已置顶,见集成 docstring)
    base = {"合同": 1.0}
    chunk = {"docnum_tok": 1.0, "合同": 0.5}  # 目标 chunk:含发文字号 token
    emb = _FakeEmbed({"银保监发〔2021〕5号": {"docnum_tok": 1.0}})
    out = augment_sparse(
        "银保监发〔2021〕5号 合同", base, embed=emb, docnum_on=True, docnum_factor=2.0
    )
    assert _ip(out, chunk) > _ip(base, chunk)  # 0.5 → 2.5(发文字号 token 加权并入)


def test_augment_expand_strictly_raises_target_ip():
    # 词典扩展同理:注入法言词**严格增大**与"含法言词 chunk"的 sparse 内积(从无到有命中)。
    base = {"提法": 1.0}
    chunk = {"legal_tok": 1.0}  # 目标 chunk:只含法言词 token(口语 query 不命中)
    emb = _FakeEmbed({"买卖时机": {"legal_tok": 1.0}})
    out = augment_sparse(
        "见底到顶提法", base, embed=emb,
        expand_on=True, expand_factor=1.0, scenario_terms={"见底到顶": ["买卖时机"]},
    )
    assert _ip(out, chunk) > _ip(base, chunk)  # 0 → 1.0


# ── T3:Retriever 接线(主 retrieve 注入;enumerate/cases 不接)─────────────
from query.config import QueryConfig  # noqa: E402
from query.retrieve.hybrid import Retriever  # noqa: E402

_QUERY = "银保监发〔2021〕5号 的处罚标准"
_BASE = {"q": 1.0}
_SPAN = {"tok_a": 0.5}  # 发文字号 span "银保监发〔2021〕5号" 的预设 sparse


def _embed():
    table = {_QUERY: _BASE, "银保监发〔2021〕5号": _SPAN}
    return SimpleNamespace(
        embed=lambda texts: [
            SimpleNamespace(dense=[0.1], sparse=dict(table.get(t, {}))) for t in texts
        ]
    )


def _milvus(cap):
    def _search(dense, sparse, *, topk, include_superseded=False, corpus=None,
                extra_expr=None, with_text=False):
        cap.append({"dense": dense, "sparse": sparse})
        return SimpleNamespace(hits=[], retrieval_mode="hybrid")
    return SimpleNamespace(search=_search)


def test_retrieve_both_off_byte_equiv():
    # 双关默认关 → search 收到 emb.sparse 原样 + dense 恒等(byte 等价 + 只动 sparse)
    cap: list = []
    Retriever(_embed(), _milvus(cap), QueryConfig()).retrieve(_QUERY)
    assert cap[0]["sparse"] == _BASE  # 未增强
    assert cap[0]["dense"] == [0.1]  # dense 恒等


def test_retrieve_docnum_boost_augments():
    cap: list = []
    r = Retriever(_embed(), _milvus(cap), QueryConfig(docnum_boost=True, docnum_boost_factor=2.0))
    r.retrieve(_QUERY)
    assert cap[0]["sparse"]["tok_a"] == 2.0 * 0.5  # 发文字号 token 并入
    assert cap[0]["sparse"]["q"] == 1.0  # base 保留
    assert cap[0]["dense"] == [0.1]  # dense 不变


def test_retrieve_scenario_expand_augments(tmp_path):
    csv_path = tmp_path / "d.csv"
    csv_path.write_text("oral_term,legal_terms\n代客理财,受托理财\n", encoding="utf-8")
    table = {"代客理财违规吗": {"q": 1.0}, "受托理财": {"tok_b": 0.4}}
    emb = SimpleNamespace(
        embed=lambda texts: [
            SimpleNamespace(dense=[0.1], sparse=dict(table.get(t, {}))) for t in texts
        ]
    )
    cap: list = []
    cfg = QueryConfig(scenario_expand=True, scenario_terms_path=str(csv_path))
    r = Retriever(emb, _milvus(cap), cfg)
    r.retrieve("代客理财违规吗")
    assert cap[0]["sparse"]["tok_b"] == 0.4  # 法言词 token 注入(扩命中面)


def test_retrieve_enumerate_not_augmented():
    # R4 枚举不接提权:即便 docnum_boost 开,retrieve_enumerate 仍用 emb.sparse 原样
    cap: list = []
    r = Retriever(_embed(), _milvus(cap), QueryConfig(docnum_boost=True))
    r.retrieve_enumerate(_QUERY)
    assert cap[0]["sparse"] == _BASE
