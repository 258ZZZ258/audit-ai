from pipeline.supervision.extraction_benchmark import (
    challenge_dataset,
    dataset,
    inputs,
    metrics,
    score,
)


def prediction(value="已完成", kind="RECTIFICATION", org="ORG-A"):
    return {
        "factType": kind,
        "organizationIds": [org],
        "values": {"status": {"value": value, "evidenceId": "E", "quote": "事项甲已完成"}},
    }


def test_duplicates_and_wrong_values_are_not_free_true_positives():
    gold = [
        {
            "type": "RECTIFICATION",
            "org": "ORG-A",
            "anchor": "事项甲",
            "fields": {"status": "已完成"},
        }
    ]
    scored = score(gold, [prediction(), prediction()])
    assert scored["facts"] == metrics(1, 1, 0)
    assert scored["fields"] == metrics(1, 1, 0)
    assert score(gold, [prediction("未完成")])["fields"] == metrics(0, 1, 1)
    assert score(gold, [prediction(org="ORG-B")])["facts"] == metrics(0, 1, 1)
    assert score(gold, [prediction(kind="FINDING")])["facts"] == metrics(0, 1, 1)


def test_empty_denominators_and_missing_records():
    assert score([], [prediction()])["facts"] == metrics(0, 1, 0)
    assert score([], [])["facts"]["recall"] is None
    assert metrics(0, 0, 2)["recall"] == 0


def test_field_scoring_does_not_depend_on_duplicate_order():
    gold = [
        {
            "type": "RECTIFICATION",
            "org": "ORG-A",
            "anchor": "事项甲",
            "fields": {"status": "已完成"},
        }
    ]
    predictions = [prediction(), prediction("未完成")]
    assert score(gold, predictions)["fields"] == score(gold, predictions[::-1])["fields"]


def test_fixed_labels_are_not_in_model_input():
    assert len(dataset()) == 12
    assert sum(len(case["gold"]) for case in dataset()) == 19
    for case in dataset():
        request, ir = inputs(case)
        assert "gold" not in request.model_dump()
        assert len(ir.blocks) == len(case["rows"])


def test_challenges_and_punctuation_metric_keep_errors_visible():
    assert len(challenge_dataset()) == 6
    assert sum(len(case["gold"]) for case in challenge_dataset()) == 8
    gold = [
        {
            "type": "RECTIFICATION",
            "org": "ORG-A",
            "anchor": "事项甲",
            "fields": {"status": "已完成"},
        }
    ]
    result = score(gold, [prediction("已完成。")])
    assert result["fields"]["tp"] == 0
    assert result["normalizedFields"]["tp"] == 1
    assert score(gold, [prediction("未完成")])["normalizedFields"]["tp"] == 0
