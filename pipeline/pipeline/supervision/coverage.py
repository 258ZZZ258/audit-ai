"""Structure-aware grouping and additive, evidence-bound omission review."""

import json
import re

from pydantic import Field

from common.supervision import Contract, EvidenceCitation, ExtractedValue, FactCandidate, ModelFacts
from pipeline.supervision.prompting import load_prompt


class Supplement(Contract):
    factIndex: int = Field(ge=0)
    anchor: EvidenceCitation
    values: dict[str, ExtractedValue] = Field(min_length=1)


class CoverageReview(Contract):
    checkedEvidenceIds: list[str]
    additions: list[FactCandidate]
    supplements: list[Supplement]


def group_evidence(evidence, budget):
    """Never truncate a row/page; prefer explicit new-matter boundaries."""
    units, unit = [], []
    for item in evidence:
        if len(item.text) > budget:
            raise ValueError("Evidence exceeds max_evidence_chars; increase configured capacity")
        numerals = r"[一二三四五六七八九十\d]+"
        boundary = re.match(
            rf"^\s*(?:问题{numerals}|第{numerals}[章节]|[一二三四五六七八九十]+、)", item.text,
        )
        if unit and (boundary or item.locatorType == "TABLE_ROW"):
            units.append(unit)
            unit = []
        unit.append(item)
    if unit:
        units.append(unit)
    groups, current, size = [], [], 0
    for unit in units:
        unit_size = sum(len(item.text) for item in unit)
        if current and size + unit_size > budget:
            groups.append(current)
            current, size = [], 0
        for item in unit:
            if current and size + len(item.text) > budget:
                groups.append(current)
                current, size = [], 0
            current.append(item)
            size += len(item.text)
    if current:
        groups.append(current)
    return groups


def review_coverage(body, candidates, client, *, retry=False):
    prompt = load_prompt("coverage-prompt.txt")
    if retry:
        prompt += (
            '\n上次响应格式校验失败。本次顶层只能有checkedEvidenceIds、additions、'
            'supplements三个数组键，不允许type、json_object或其他包装键。'
            '值字段必须包含value、evidenceId、quote；重新完整检查后返回合法JSON。'
        )
    review = CoverageReview.model_validate(client.chat_json(prompt, json.dumps({
        **body, "existingFacts": candidates.model_dump()["facts"],
    }, ensure_ascii=False)))
    sources = {e["evidenceId"]: e["text"] for e in body["evidence"]}
    if (len(review.checkedEvidenceIds) != len(sources)
            or set(review.checkedEvidenceIds) != set(sources)):
        raise ValueError("Incomplete coverage review")
    facts = [fact.model_copy(deep=True) for fact in candidates.facts]
    targets = set()
    for supplement in review.supplements:
        if supplement.factIndex >= len(facts):
            raise ValueError("Unknown supplement target")
        target = facts[supplement.factIndex]
        citations = [c for value in target.values.values() for c in value.citations()]
        if supplement.anchor not in citations:
            raise ValueError("Supplement must anchor to an existing fact citation")
        if supplement.anchor.quote not in sources.get(supplement.anchor.evidenceId, ""):
            raise ValueError("Invalid supplement anchor")
        for field, value in supplement.values.items():
            if (supplement.factIndex, field) in targets:
                raise ValueError("Coverage review cannot overwrite existing fields")
            if field in target.values:
                original = target.values[field]
                expandable = {"problem", "issueDescription", "specificMatter", "relatedMatter",
                              "caseFacts", "rectificationMeasure", "rectificationResult",
                              "progress"}
                preserved = all(c in value.citations() for c in original.citations())
                if field not in expandable or original.value not in value.value or not preserved:
                    raise ValueError("Coverage review cannot overwrite existing fields")
            targets.add((supplement.factIndex, field))
            target.values[field] = value
    facts.extend(review.additions)
    # All returned fields still pass the original scope and verbatim validation downstream.
    return ModelFacts(facts=facts), {
        "code": "COVERAGE_REVIEWED", "checkedEvidenceIds": review.checkedEvidenceIds,
        "addedFacts": len(review.additions), "supplementedFields": len(targets),
    }
