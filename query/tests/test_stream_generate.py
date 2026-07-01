"""T10(SPEC-API §6.2 / v1.5 §7.2):流式 R1 生成(离线,stub + monkeypatch PG 回查)。

验:两次调用编排 —— 有忠实引用 → 先 delta* 后 result(引用与同步一致、无裸结论);无忠实引用/
degraded → 流式前降级拒答(无 delta)。真 gateway 流式在 _integration。
"""

from __future__ import annotations

import query.generate.r1_evidence as mod
from query.contract import Citation, RouteType
from query.generate.r1_evidence import generate_evidence_stream
from query.llm.stub import StubLLMClient
from query.retrieve.hybrid import Candidate

_BARE = ("违规", "违法", "合规", "合法")


def _cand(cid, degraded=False):
    return Candidate(cid, 1.0, "P-INT", "dv1", "第一条", 1, degraded, "hybrid")


def _patch(monkeypatch, texts, anchors):
    monkeypatch.setattr(
        mod, "fetch_texts", lambda pg, ids: {i: texts[i] for i in ids if i in texts}
    )
    monkeypatch.setattr(
        mod, "fetch_anchors", lambda pg, ids: {i: anchors[i] for i in ids if i in anchors}
    )


def test_stream_deltas_then_result_with_faithful_citations(monkeypatch):
    _patch(
        monkeypatch,
        {"a1": "第一条 相关制度条款全文……"},
        {"a1": Citation(clause_id="a1", doc_title="《细则》", status="effective")},
    )
    events = list(generate_evidence_stream("q", [_cand("a1")], pg=None, llm=StubLLMClient()))
    kinds = [e[0] for e in events]
    assert "delta" in kinds and kinds[-1] == "result"       # 先流式后收尾
    deltas = "".join(e[1] for e in events if e[0] == "delta")
    assert deltas                                            # 真有流式文本
    result = events[-1][1]
    assert result.route_type is RouteType.EVIDENCE
    assert [c.clause_id for c in result.citations] == ["a1"]  # 引用与同步一致(chat_json 选)
    answer = "".join(b.content for b in result.answer_blocks)
    assert all(t not in answer for t in _BARE)              # 无裸结论


class _BareLLM:
    """chat_json 选 a1;stream 跨 chunk 吐出含裸结论的句子(测句段缓冲过检,F1 critical)。"""

    def chat_json(self, system, user):
        import re

        ids = re.findall(r"\[\[clause_id:([^\]]+)\]\]", user)
        return {"answer": "x", "cited_clause_ids": ids[:1]}

    def stream(self, system, user):
        yield from ["该行为构成", "违", "规。", "依据第三条应当留痕。"]


def test_stream_sanitizes_bare_conclusion_across_chunks(monkeypatch):
    _patch(monkeypatch, {"a1": "第一条 全文"}, {"a1": Citation(clause_id="a1", status="effective")})
    events = list(generate_evidence_stream("q", [_cand("a1")], pg=None, llm=_BareLLM()))
    deltas = [d for k, d in events if k == "delta"]
    for d in deltas:                          # 每个流出的 delta 都无裸结论(句段过 sanitize)
        assert all(t not in d for t in _BARE)
    result = events[-1][1]
    answer = "".join(b.content for b in result.answer_blocks)
    assert all(t not in answer for t in _BARE)
    assert "".join(deltas) == answer          # 流出拼接 == 存档答复(一致)


def test_stream_no_faithful_citation_refuses_before_streaming(monkeypatch):
    _patch(monkeypatch, {}, {})   # 无 text → 无 blocks → 无引用
    events = list(
        generate_evidence_stream(
            "q", [], pg=None, llm=StubLLMClient(), exhausted_scope=["投顾业务"]
        )
    )
    assert [e[0] for e in events] == ["result"]             # 无 delta,直接拒答
    assert events[0][1].route_type is RouteType.REFUSE
    assert events[0][1].exhausted_scope == ["投顾业务"]


def test_stream_degraded_excluded_refuses(monkeypatch):
    _patch(monkeypatch, {"a1": "文"}, {"a1": Citation(clause_id="a1")})
    events = list(
        generate_evidence_stream("q", [_cand("a1", degraded=True)], pg=None, llm=StubLLMClient())
    )
    assert [e[0] for e in events] == ["result"]             # degraded 排除 → 无上下文 → 拒答
    assert events[0][1].route_type is RouteType.REFUSE
