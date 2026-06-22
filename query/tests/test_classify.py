"""T7:N2 场景分类(规则,含 §4.3 优先级)+ 涉及事项 / entity_type 词典抽取。"""

from __future__ import annotations

import pytest

from query.understand.classify import SceneType, classify, classify_scene, extract_terms


@pytest.mark.parametrize(
    "query, scene",
    [
        ("费用报销发票三个月的规定在哪里", SceneType.EVIDENCE),
        ("二维码介绍开户是否违规", SceneType.BEHAVIOR),
        ("哪些制度规定了信息披露", SceneType.ENUMERATE),
        ("合同管理办法什么时候修订的", SceneType.CHANGE),
        ("有没有类似的处罚案例", SceneType.CASE),
        ("哪些板块处罚高发", SceneType.STATISTICAL),
        ("什么是全权委托", SceneType.DEFINITION),
    ],
)
def test_classify_scene(query, scene):
    assert classify_scene(query) == scene


def test_priority_behavior_over_enumerate():
    # 同时命中"列举(哪些规定)"与"判定(能不能)" → 判定优先(§4.3)
    assert classify_scene("哪些规定明确代客理财能不能做") is SceneType.BEHAVIOR


def test_extract_terms_substring_dedup():
    terms = ["投顾业务", "信息披露", "投顾业务"]
    assert extract_terms("关于投顾业务和信息披露的要求", terms) == ["投顾业务", "信息披露"]


def test_classify_aggregates_matters_and_entities():
    s = classify(
        "C类营业部投顾业务是否违规", biz_terms=["投顾业务"], entity_terms=["C类营业部"]
    )
    assert s.scene_type is SceneType.BEHAVIOR
    assert s.matters == ["投顾业务"]
    assert s.entity_types == ["C类营业部"]
