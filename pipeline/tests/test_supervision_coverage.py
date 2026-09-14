import json

import pytest
from test_supervision_extraction import Extractor, make_ir, request_data

from common.ir import Block, BlockType, SourceFormat
from common.supervision import ModelFacts, SupervisionExtractRequest
from pipeline.supervision.coverage import group_evidence, review_coverage
from pipeline.supervision.extract import evidence_from_ir, prepare_extraction


def test_coverage_schema_retry_explains_allowed_shape_without_relaxing_it():
    class Flaky(Extractor):
        review_calls = 0

        def chat_json(self, system, user):
            body = json.loads(user)
            if "existingFacts" not in body:
                return super().chat_json(system, user)
            self.review_calls += 1
            result = {"checkedEvidenceIds": [e["evidenceId"] for e in body["evidence"]],
                      "additions": [], "supplements": []}
            if self.review_calls == 1:
                result["type"] = "json_object"
            else:
                assert "上次响应格式校验失败" in system
            return result

    client = Flaky()
    output = prepare_extraction(SupervisionExtractRequest.model_validate(request_data()),
                                make_ir(), client=client, max_evidence_chars=1000,
                                coverage_review=True)
    assert client.review_calls == 2
    assert len(output["facts"]) == 1
    assert any(c.get("code") == "COVERAGE_OUTPUT_RETRY" for c in output["metadataChecks"])


class Reviewer(Extractor):
    def __init__(self, mode="supplement"):
        super().__init__()
        self.mode = mode

    def chat_json(self, system, user):
        body = json.loads(user)
        if "existingFacts" not in body:
            return super().chat_json(system, user)
        self.inputs.append(body)
        result = {"checkedEvidenceIds": [e["evidenceId"] for e in body["evidence"]],
                  "additions": [], "supplements": []}
        if self.mode == "missing-coverage":
            result["checkedEvidenceIds"].pop()
        if self.mode in ("supplement", "forged", "overwrite", "target", "anchor"):
            field = "problem" if self.mode == "overwrite" else "rectification"
            value = {"value": "已补记录", "quote": "已补记录",
                     "evidenceId": body["evidence"][1]["evidenceId"]}
            if self.mode == "forged":
                value["quote"] = "原文不存在"
            anchor = body["existingFacts"][0]["values"]["problem"]
            result["supplements"] = [{
                "factIndex": 99 if self.mode == "target" else 0,
                "anchor": {"evidenceId": anchor["evidenceId"],
                           "quote": "假的锚点" if self.mode == "anchor" else anchor["quote"]},
                "values": {field: value},
            }]
        if self.mode == "add":
            row = body["evidence"][2]
            result["additions"] = [{"ruleId": "REG-1", "factType": "RECTIFICATION",
                                    "organizationIds": ["ORG-B"], "values": {
                                        "rectification": {"value": "正在整改", "quote": "正在整改",
                                                          "evidenceId": row["evidenceId"]}}}]
        return result


def test_review_adds_missing_field_and_preserves_original_fact():
    result = prepare_extraction(SupervisionExtractRequest.model_validate(request_data()), make_ir(),
                                client=Reviewer(), max_evidence_chars=16000, coverage_review=True)
    assert len(result["facts"]) == 1
    assert result["facts"][0]["values"]["problem"]["value"] == "记录不完整"
    assert result["facts"][0]["values"]["rectification"]["value"] == "已补记录"
    assert result["facts"][0]["missingRequiredFields"] == []
    assert result["facts"][0]["confirmationStatus"] == "PENDING_REVIEW"
    assert any(c.get("supplementedFields") == 1 for c in result["metadataChecks"])


def test_review_recovers_missing_independent_record_without_new_finding():
    result = prepare_extraction(SupervisionExtractRequest.model_validate(request_data()), make_ir(),
                                client=Reviewer("add"), max_evidence_chars=16000,
                                coverage_review=True)
    assert len(result["facts"]) == 2
    assert result["facts"][1]["factType"] == "RECTIFICATION"
    assert result["facts"][1]["organizationIds"] == ["ORG-B"]


@pytest.mark.parametrize("mode", ["missing-coverage", "forged", "overwrite", "target", "anchor"])
def test_invalid_review_fails_whole_extraction(mode):
    with pytest.raises(ValueError):
        prepare_extraction(SupervisionExtractRequest.model_validate(request_data()), make_ir(),
                           client=Reviewer(mode), max_evidence_chars=16000, coverage_review=True)


def test_grouping_prefers_numbered_matters_without_dropping_evidence():
    ir = make_ir()
    ir.source_format = SourceFormat.DOCX
    ir.blocks = [Block(index=i, type=BlockType.PARAGRAPH, text=text) for i, text in enumerate([
        "问题一：权限管理", "该问题要求三个月整改", "问题二：合同管理", "该问题正在处理",
    ])]
    evidence = evidence_from_ir(SupervisionExtractRequest.model_validate(request_data()), ir)
    groups = group_evidence(evidence, sum(len(e.text) for e in evidence[:2]) + 2)
    assert [len(group) for group in groups] == [2, 2]
    assert [e for group in groups for e in group] == evidence


def test_description_expansion_must_preserve_existing_text_and_all_citations():
    original = {"value": "记录不完整", "quote": "记录不完整", "evidenceId": "E1"}
    facts = ModelFacts.model_validate({"facts": [{"ruleId": "REG-1",
        "organizationIds": ["ORG-A"], "values": {"problem": original}}]})
    body = {"evidence": [{"evidenceId": "E1", "text": "记录不完整"},
                         {"evidenceId": "E2", "text": "涉及两份记录"}]}

    class Client:
        def chat_json(self, system, user):
            return {"checkedEvidenceIds": ["E1", "E2"], "additions": [], "supplements": [{
                "factIndex": 0, "anchor": {"evidenceId": "E1", "quote": "记录不完整"},
                "values": {"problem": {**original, "value": "记录不完整，涉及两份记录",
                    "supportingEvidence": [{"evidenceId": "E2", "quote": "涉及两份记录"}]}}}]}

    reviewed, _ = review_coverage(body, facts, Client())
    assert len(reviewed.facts[0].values["problem"].citations()) == 2
    assert facts.facts[0].values["problem"].value == "记录不完整"


def test_boundary_supplements_only_explicit_existing_target():
    ir = make_ir()
    ir.source_format = SourceFormat.DOCX
    ir.blocks = [Block(index=i, type=BlockType.PARAGRAPH, text=text) for i, text in enumerate([
        "背景信息" * 10, "甲单位记录不完整。", "问题一整改进展：甲单位已补记录。",
    ])]

    class Boundary(Reviewer):
        def chat_json(self, system, user):
            body = json.loads(user)
            if "existingFacts" not in body:
                if body["evidence"][0]["text"].startswith("问题一"):
                    return {"facts": []}
                result = Extractor.chat_json(self, system, user)
                anchor = body["evidence"][-1]
                result["facts"][0]["values"]["problem"].update(
                    evidenceId=anchor["evidenceId"], quote=anchor["text"],
                )
                return result
            if not body.get("boundaryOnly"):
                return {"checkedEvidenceIds": [e["evidenceId"] for e in body["evidence"]],
                        "additions": [], "supplements": []}
            return super().chat_json(system, user)

    result = prepare_extraction(SupervisionExtractRequest.model_validate(request_data()), ir,
                                client=Boundary(), max_evidence_chars=52, coverage_review=True)
    assert len(result["facts"]) == 1
    assert result["facts"][0]["values"]["rectification"]["value"] == "已补记录"
    assert any(c["code"] == "BOUNDARY_REVIEWED" for c in result["metadataChecks"] if "code" in c)
