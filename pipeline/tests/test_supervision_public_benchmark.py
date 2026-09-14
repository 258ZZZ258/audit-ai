from copy import deepcopy

from pipeline.supervision.public_benchmark import satisfies, score_public


def sample():
    gold = [
        {
            "id": "a",
            "type": "RECTIFICATION",
            "orgs": ["A"],
            "identity": {"allOf": [["洗车费"]]},
            "fields": {
                "issueDescription": {"allOf": [["洗车费"]]},
                "rectificationStatus": {"equals": ["部分完成"]},
            },
        }
    ]
    evidence = {"E": {"text": "洗车费仍在追索，整改部分完成。其他问题已完成。"}}
    prediction = {
        "factType": "RECTIFICATION",
        "organizationIds": ["A"],
        "values": {
            "issueDescription": {
                "value": "洗车费仍在追索",
                "evidenceId": "E",
                "quote": "洗车费仍在追索",
            },
            "rectificationStatus": {
                "value": "部分完成",
                "evidenceId": "E",
                "quote": "整改部分完成",
            },
        },
    }
    return gold, evidence, prediction


def test_status_negation_and_duplicate_predictions():
    gold, evidence, p = sample()
    scored = score_public(gold, [p, deepcopy(p)], evidence)
    assert scored["facts"]["tp"] == 1
    assert scored["facts"]["fp"] == 1
    assert scored["fieldRubric"]["tp"] == 2
    p["values"]["rectificationStatus"]["value"] = "已完成"
    scored = score_public(gold, [p], evidence)
    assert scored["fieldRubric"]["tp"] == 1
    assert scored["fieldRubric"]["fp"] == 1
    assert scored["fieldRubric"]["fn"] == 1


def test_same_page_without_relevant_quote_is_not_a_match():
    gold, evidence, p = sample()
    for v in p["values"].values():
        v["quote"] = "其他问题已完成"
    assert score_public(gold, [p], evidence)["facts"]["tp"] == 0


def test_verbatim_citation_cannot_rescue_wrong_org_or_missing_identity():
    gold, evidence, p = sample()
    p["organizationIds"] = ["B"]
    assert score_public(gold, [p], evidence)["facts"]["tp"] == 0
    p["organizationIds"] = ["A"]
    p["values"]["issueDescription"]["value"] = "其他问题"
    assert score_public(gold, [p], evidence)["facts"]["tp"] == 0


def test_nonverbatim_quote_is_not_a_match():
    gold, evidence, p = sample()
    p["values"]["issueDescription"]["quote"] = "伪造洗车费"
    assert score_public(gold, [p], evidence)["facts"]["tp"] == 0


def test_empty_denominator_and_unexpected_fields():
    gold, evidence, p = sample()
    assert score_public([], [], evidence)["facts"]["precision"] is None
    p["values"]["invented"] = deepcopy(p["values"]["issueDescription"])
    assert score_public(gold, [p], evidence)["fieldRubric"]["fp"] == 1
    assert score_public([], [p], evidence)["facts"]["fp"] == 1


def test_rubric_preserves_negation_and_all_required_facts():
    r = {"allOf": [["52.9万元"], ["追索", "追讨"]], "noneOf": ["全部完成"]}
    assert satisfies("收回 52.9 万元，其他仍在追讨。", r)
    assert not satisfies("收回52.9万元，已全部完成，无须追索", r)
    assert not satisfies("收回52.9万元", r)


def test_numeric_rubric_does_not_match_a_suffix_of_another_amount():
    r = {"allOf": [["20万元"]]}
    assert satisfies("罚款20万元", r)
    assert not satisfies("罚款120万元", r)
    assert not satisfies("罚款1,020万元", r)
    assert not satisfies("罚款1.20万元", r)
    assert satisfies("涉及4,650.00万元", {"allOf": [["4650"], ["万元"]]})
    assert not satisfies("涉及14650万元", {"allOf": [["4650"]]})
    assert not satisfies("涉及-4650万元", {"allOf": [["4650"]]})


def test_fullwidth_thousands_separator_only_in_valid_numeric_groups():
    assert satisfies("合计10，338万元", {"allOf": [["10338"]]})
    assert not satisfies("合计10，338万元", {"allOf": [["338"]]})
    assert not satisfies("金额10，33万元", {"allOf": [["1033"]]})
    assert not satisfies("金额-10，338万元", {"allOf": [["10338"]]})
