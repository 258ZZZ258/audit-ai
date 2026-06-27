"""T2.3a 业务域 L2 LLM 打标(§7.1):整篇制度 → 业务域多值(dict_biz_domains 约束)。

纯助手单元(免栈、免真 LLM,注入 ``FakeClient``)。镜像 E2/case_l2 纪律:字典服务端裁剪 +
不臆测 + 字典空不调 LLM。写权威字段(``doc_versions.biz_domains`` + ``biz_domain_source``)的装配
在 s4_meta(T2.3b),本测只覆盖纯打标 + 裁字典。
"""

from __future__ import annotations

from pipeline.meta import l2_llm


class FakeClient:
    def __init__(self, response=None):
        self._response = response if response is not None else {}
        self.calls = 0

    def chat_json(self, system: str, user: str):
        self.calls += 1
        return self._response


def test_build_biz_prompt_includes_allowed_and_rules():
    system, user = l2_llm.build_biz_prompt("某券商经纪业务管理办法……", ["经纪业务", "投行业务"])
    assert "严格来自" in system and "不臆测" in system
    assert "biz_domains" in system
    assert "经纪业务" in user and "投行业务" in user
    assert "经纪业务管理办法" in user  # 文档(节选)进 user


def test_tag_biz_domain_enforces_dict():
    allowed = ["经纪业务", "投行业务", "资产管理"]
    client = FakeClient({"biz_domains": ["经纪业务", "火星业务"]})
    out = l2_llm.tag_biz_domain(client, "doc", allowed)
    assert out == ["经纪业务"]  # 字典外 火星业务 被裁


def test_tag_biz_domain_multi_value_dedup_preserve_order():
    allowed = ["经纪业务", "投行业务", "资产管理"]
    client = FakeClient({"biz_domains": ["资产管理", "经纪业务", "资产管理"]})
    out = l2_llm.tag_biz_domain(client, "doc", allowed)
    assert out == ["资产管理", "经纪业务"]  # 去重保序


def test_tag_biz_domain_empty_dict_skips_llm():
    client = FakeClient({"biz_domains": ["x"]})
    out = l2_llm.tag_biz_domain(client, "doc", [])
    assert out == []
    assert client.calls == 0  # 字典空 → 不调 LLM(consumed-when-present)


def test_tag_biz_domain_handles_bad_response():
    allowed = ["经纪业务"]
    assert l2_llm.tag_biz_domain(FakeClient("nope"), "doc", allowed) == []
    assert l2_llm.tag_biz_domain(FakeClient({}), "doc", allowed) == []
    assert l2_llm.tag_biz_domain(FakeClient({"biz_domains": "not-list"}), "doc", allowed) == []


# ── T2.3b biz_l2_decision 纯逻辑:manifest 优先/冲突 + profile 分档 + 抽检 ──────────
def test_decision_manifest_priority_no_conflict():
    biz, src, review = l2_llm.biz_l2_decision(
        "P-INT", "经纪业务", ["经纪业务"], sampling_rate=1.0, sample_key="dv1"
    )
    assert biz == ["经纪业务"] and src == "manifest" and review is False


def test_decision_manifest_conflict_forces_review():
    # manifest 给「经纪业务」,LLM 给「投行业务」(不含 manifest 值)→ 冲突 → 人工
    biz, src, review = l2_llm.biz_l2_decision(
        "P-EXT", "经纪业务", ["投行业务"], sampling_rate=0.0, sample_key="dv1"
    )
    assert biz == ["经纪业务"] and src == "manifest" and review is True


def test_decision_manifest_priority_llm_empty_no_conflict():
    biz, src, review = l2_llm.biz_l2_decision(
        "P-EXT", "经纪业务", [], sampling_rate=0.0, sample_key="dv1"
    )
    assert biz == ["经纪业务"] and src == "manifest" and review is False


def test_decision_pint_llm_candidate_forces_review():
    # 内规无 manifest:LLM 候选恒入 META_REVIEW(即便 sampling_rate=0)
    biz, src, review = l2_llm.biz_l2_decision(
        "P-INT", None, ["经纪业务", "投行业务"], sampling_rate=0.0, sample_key="dv1"
    )
    assert biz == ["经纪业务", "投行业务"] and src == "llm" and review is True


def test_decision_pext_direct_land_no_sampling():
    biz, src, review = l2_llm.biz_l2_decision(
        "P-EXT", None, ["经纪业务"], sampling_rate=0.0, sample_key="dv1"
    )
    assert biz == ["经纪业务"] and src == "llm" and review is False  # 直落


def test_decision_direct_land_sampled_for_review():
    # sampling_rate=1.0 → 抽中 → spot-check 复核(直落 profile 也入闸)
    for corpus in ("P-EXT", "P-QA", "P-CASE"):
        _biz, _src, review = l2_llm.biz_l2_decision(
            corpus, None, ["经纪业务"], sampling_rate=1.0, sample_key="dv1"
        )
        assert review is True


def test_decision_no_manifest_no_llm_writes_nothing():
    biz, src, review = l2_llm.biz_l2_decision(
        "P-INT", None, [], sampling_rate=1.0, sample_key="dv1"
    )
    assert biz is None and src is None and review is False


def test_sampled_deterministic_bounds():
    assert l2_llm._sampled("anykey", 0.0) is False  # rate 0 → 永不抽
    assert l2_llm._sampled("anykey", 1.0) is True  # rate 1 → 必抽
    # 同 key 同 rate 恒同判(确定性,重跑可复现)
    assert l2_llm._sampled("dvX", 0.5) == l2_llm._sampled("dvX", 0.5)
