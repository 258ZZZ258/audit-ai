import json

import pytest
from test_supervision_extraction import make_ir, request_data

from common.supervision import FactCandidate, SupervisionExtractRequest
from pipeline.supervision.extract import evidence_from_ir
from pipeline.supervision.quote_repair import ensure_citations, split_pdf_citation


def setup():
    evidence = evidence_from_ir(SupervisionExtractRequest.model_validate(request_data()), make_ir())
    source = evidence[0]
    fact = FactCandidate(ruleId="REG-1", organizationIds=["ORG-A"], values={
        "problem": {"value": "记录不完整", "evidenceId": source.evidenceId,
                    "quote": "模型拼接的引用", "supportingEvidence": [
                        {"evidenceId": source.evidenceId, "quote": "甲单位"}]},
    })
    return fact, {e.evidenceId: e for e in evidence}, source


@pytest.mark.parametrize("mode", [
    "valid", "changed-value", "lost-support", "unknown-source", "extra-field",
])
def test_repairs_only_references_and_keeps_business_value_and_good_evidence(mode):
    fact, sources, source = setup()
    original = fact.model_dump()

    class Client:
        calls = 0

        def chat_json(self, system, user):
            self.calls += 1
            body = json.loads(user)
            value = body["values"]["problem"]
            value["quote"] = source.text
            value.pop("value")
            if mode == "changed-value":
                value["value"] = "没有问题"
            if mode == "lost-support":
                value["supportingEvidence"] = []
            if mode == "unknown-source":
                value["evidenceId"] = "other-document"
            values = {"problem": value}
            if mode == "extra-field":
                values["invented"] = value
            return {"references": values}

    client = Client()
    if mode == "valid":
        checks = ensure_citations(fact, sources, client, 2, lambda s, q: None)
        assert fact.values["problem"].quote == source.text
        assert fact.values["problem"].value == original["values"]["problem"]["value"]
        assert checks[-1]["code"] == "QUOTE_REFERENCES_REPAIRED"
    else:
        with pytest.raises(ValueError, match="non-verbatim"):
            ensure_citations(fact, sources, client, 2, lambda s, q: None)
        assert fact.model_dump() == original
    assert client.calls == 1


def test_valid_citations_make_no_model_call_and_one_attempt_disables_repair():
    fact, sources, source = setup()
    with pytest.raises(ValueError, match="non-verbatim"):
        ensure_citations(fact, sources, None, 1, lambda s, q: None)
    fact.values["problem"].quote = source.text
    assert ensure_citations(fact, sources, None, 2, lambda s, q: None) == []


@pytest.mark.parametrize("quote,expected", [
    ("违规招标确定合作方\n导致收入减少", 2),
    ("导致收入减少\n违规招标确定合作方", 1),
    ("违规招标确定合作方\n导致收入增加", 1),
    ("违规招标确定合作方\n重复文字", 1),
])
def test_interleaved_pdf_lines_require_exact_unique_ordered_segments(quote, expected):
    fact, sources, source = setup()
    source.locatorType = "PAGE_TEXT"
    source.text = "违规招标确定合作方\n另一列措施\n导致收入减少\n重复文字\n重复文字"
    citation = fact.values["problem"].citations()[0].model_copy(update={"quote": quote})
    parts = split_pdf_citation(citation, sources)
    assert len(parts) == expected
    if expected == 2:
        assert all(c.quote in source.text for c in parts)
    source.locatorType = "PARAGRAPH"
    assert split_pdf_citation(citation, sources) == [citation]
