import pytest
from test_supervision_extraction import Extractor, make_ir, request_data

from common.supervision import SupervisionExtractRequest
from pipeline.supervision.extract import prepare_extraction
from pipeline.supervision.normalization import normalize_status


@pytest.mark.parametrize("source,expected", [
    ("已全部完成。", "已完成"), ("正在整改", "进行中"),
    ("部分已完成", "部分完成"), ("尚未完成", "未完成"),
    ("未全部完成", "未完成"), ("预计完成", "预计完成"),
    ("计划下月全部完成", "计划下月全部完成"),
    ("已完成，但验收未通过", "已完成，但验收未通过"),
    ("目前只完成了部分，仍在推进", "目前只完成了部分，仍在推进"),
])
def test_only_unambiguous_full_value_aliases_are_normalized(source, expected):
    assert normalize_status(source) == expected


def test_status_normalization_keeps_original_quote():
    data = request_data()
    data["rules"][0]["extractFields"].append({"key": "rectificationStatus", "description": "状态"})
    ir = make_ir()
    ir.blocks[0].text = "甲单位已全部完成。"

    def mutate(fact):
        source = fact["values"]["problem"]
        fact["values"]["rectificationStatus"] = {
            "value": "已全部完成。", "evidenceId": source["evidenceId"], "quote": "已全部完成。",
        }

    result = prepare_extraction(SupervisionExtractRequest.model_validate(data), ir,
                                client=Extractor(mutate), max_evidence_chars=16000)
    status = result["facts"][0]["values"]["rectificationStatus"]
    assert status["value"] == "已完成"
    assert status["quote"] == "已全部完成。"


def test_litigation_rule_supplies_missing_type_without_model_guess():
    data = request_data()
    data["rules"][0]["reportSection"] = "internal.daily.litigation"
    result = prepare_extraction(SupervisionExtractRequest.model_validate(data), make_ir(),
                                client=Extractor(), max_evidence_chars=16000)
    assert result["facts"][0]["factType"] == "LITIGATION"


def test_missing_type_is_explicit_and_accountability_rule_needs_action():
    data = request_data()
    data["rules"][0]["reportSection"] = "internal.accountability"
    data["rules"][0]["extractFields"].append({"key": "accountabilityAction", "description": "措施"})
    result = prepare_extraction(SupervisionExtractRequest.model_validate(data), make_ir(),
                                client=Extractor(), max_evidence_chars=16000)
    assert result["facts"][0]["factType"] == "UNSPECIFIED"

    def mutate(fact):
        fact["values"]["accountabilityAction"] = dict(fact["values"]["problem"])

    result = prepare_extraction(SupervisionExtractRequest.model_validate(data), make_ir(),
                                client=Extractor(mutate), max_evidence_chars=16000)
    assert result["facts"][0]["factType"] == "ACCOUNTABILITY"
