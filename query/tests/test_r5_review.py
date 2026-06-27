"""R5-T2(单元):§9.2 多模型复核接口——toggle 关 passthrough / 开校验降级。零栈零模型。"""

from __future__ import annotations

from types import SimpleNamespace

from query.contract import AnswerBlock, BlockType
from query.judge import r5_judgment
from query.judge.review import review_tentative

# 复核证据 = 所引条款(含**正文**);仅题名/条号不足以判忠实性(R5-REVIEW-NEEDS-CLAUSE-EVIDENCE)。
_CLAUSES = [
    {
        "doc_title": "反洗钱管理办法",
        "clause_path": "第三条",
        "text": "金融机构应当对大额交易和可疑交易进行报告。",
    }
]
_BLOCKS = [AnswerBlock(BlockType.TEXT, "适用前提:开户推广;适用对象:营业部", stream=False)]


def test_review_prompt_includes_clause_text():
    # 核心:复核 prompt 必须带**条文原文**(非仅《题名》条号)——否则无从核忠实性。
    seen = {}

    def chat_json(system, user):
        seen["user"] = user
        return {"supported": True}

    qcfg = SimpleNamespace(judge_multimodel_review=True)
    review_tentative(_BLOCKS, _CLAUSES, llm=SimpleNamespace(chat_json=chat_json), qcfg=qcfg)
    assert "金融机构应当对大额交易和可疑交易进行报告" in seen["user"]  # 条文原文进 prompt


def _llm(supported: bool):
    return SimpleNamespace(chat_json=lambda system, user: {"supported": supported})


def test_review_off_passthrough():
    qcfg = SimpleNamespace(judge_multimodel_review=False)
    out = review_tentative(_BLOCKS, _CLAUSES, llm=_llm(False), qcfg=qcfg)
    assert out == _BLOCKS  # 关 → 原样(不调 LLM、不改块)


def test_review_on_unsupported_downgrades():
    qcfg = SimpleNamespace(judge_multimodel_review=True)
    out = review_tentative(_BLOCKS, _CLAUSES, llm=_llm(False), qcfg=qcfg)
    assert out[0].content != _BLOCKS[0].content  # 不支持 → 降级
    assert "待人工核实" in out[0].content


def test_review_on_supported_keeps():
    qcfg = SimpleNamespace(judge_multimodel_review=True)
    out = review_tentative(_BLOCKS, _CLAUSES, llm=_llm(True), qcfg=qcfg)
    assert out[0].content == _BLOCKS[0].content  # 支持 → 原样


def test_review_malformed_bool_fails_closed():
    # LLM05(Codex 复审):畸形/非严格-bool supported → fail closed(降级),绝不放过
    qcfg = SimpleNamespace(judge_multimodel_review=True)
    for bad in ("false", "true", 1, None, {}):  # 字符串/数字/缺值:均非 bool True → 不支持
        llm = SimpleNamespace(chat_json=lambda s, u, _b=bad: {"supported": _b})
        out = review_tentative(_BLOCKS, _CLAUSES, llm=llm, qcfg=qcfg)
        assert "待人工核实" in out[0].content, bad
    # 完全缺 supported 键 → fail closed
    llm = SimpleNamespace(chat_json=lambda s, u: {})
    assert "待人工核实" in review_tentative(_BLOCKS, _CLAUSES, llm=llm, qcfg=qcfg)[0].content


# ── T3:answer_judgment 复核客户端接线(模型分离 + 关时不建客户端,零栈)──────────────
def _run_answer_judgment(monkeypatch, *, review_on, main_llm, review_client):
    """monkeypatch r5_judgment 上游,让 answer_judgment 走到 review 行;返回 captured 字典。

    captured:{model:复核 make_llm_client 收到的 model, review_llm:review_tentative 收到的 llm,
    framing_llm:build_framing 收到的 llm, make_calls:make_llm_client 被调次数}。
    """
    captured = {"make_calls": 0}

    def fake_make(qcfg, *, model=None):
        captured["make_calls"] += 1
        captured["model"] = model
        return review_client

    def fake_review(blocks, clauses, llm, qcfg):
        captured["review_llm"] = llm
        return list(blocks)

    def fake_framing(clauses, query, llm, qcfg):
        captured["framing_llm"] = llm
        return [AnswerBlock(BlockType.TEXT, "x", stream=False)]

    monkeypatch.setattr(r5_judgment, "make_llm_client", fake_make)
    monkeypatch.setattr(r5_judgment, "review_tentative", fake_review)
    monkeypatch.setattr(r5_judgment, "build_framing", fake_framing)
    monkeypatch.setattr(r5_judgment, "resolve_cited_clauses", lambda pg, dvids: [])
    anchor = SimpleNamespace(doc_title="X办法", clause_path="第一条")
    monkeypatch.setattr(r5_judgment, "fetch_anchors", lambda pg, ids: {ids[0]: anchor})
    monkeypatch.setattr(r5_judgment, "fetch_texts", lambda pg, ids: {ids[0]: "条文"})
    retriever = SimpleNamespace(
        retrieve_cases=lambda q: [],
        retrieve=lambda q: [SimpleNamespace(chunk_id="c1", degraded=False)],
    )
    qcfg = SimpleNamespace(
        judge_multimodel_review=review_on, review_model="kimi-review", topk=8
    )
    r5_judgment.answer_judgment("q", retriever, None, main_llm, qcfg)
    return captured


def test_review_on_builds_review_client_separate_from_main(monkeypatch):
    # 复核开 → 用 review_model 建独立复核客户端传 review_tentative;框定仍用主答(§9.1 分离)。
    main_llm = SimpleNamespace(tag="main")
    review_client = SimpleNamespace(tag="review")
    cap = _run_answer_judgment(
        monkeypatch, review_on=True, main_llm=main_llm, review_client=review_client
    )
    assert cap["model"] == "kimi-review"        # 复核客户端用 review_model(非主答 llm_model)
    assert cap["review_llm"] is review_client   # review_tentative 收复核客户端
    assert cap["framing_llm"] is main_llm        # build_framing 仍用主答


def test_review_off_passthrough_no_client_built(monkeypatch):
    # 复核关 → 不建复核客户端(零网络);review_tentative 收主答 llm(passthrough)。
    main_llm = SimpleNamespace(tag="main")
    cap = _run_answer_judgment(
        monkeypatch, review_on=False, main_llm=main_llm, review_client=SimpleNamespace()
    )
    assert cap["make_calls"] == 0          # 关 → 绝不调 make_llm_client(零网络/零 key)
    assert cap["review_llm"] is main_llm   # passthrough 用主答 llm
