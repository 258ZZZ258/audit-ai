"""Bounded reference-only repair; facts and known-good citations are immutable."""

import json
from pathlib import Path

from pydantic import Field, ValidationError

from common.supervision import Contract, EvidenceCitation
from pipeline.llm_client import LLMError


class Reference(EvidenceCitation):
    supportingEvidence: list[EvidenceCitation] = Field(default_factory=list)


class Repairs(Contract):
    references: dict[str, Reference] = Field(min_length=1)


def split_pdf_citation(citation, sources):
    """Represent interleaved PDF column lines as separate exact citations."""
    source = sources.get(citation.evidenceId)
    if source is None or source.locatorType != "PAGE_TEXT" or citation.quote in source.text:
        return [citation]
    lines = [line for line in citation.quote.splitlines() if line]
    positions = [source.text.find(line) for line in lines]
    if (len(lines) < 2 or any(p < 0 or source.text.count(line) != 1
                              for p, line in zip(positions, lines, strict=True))
            or any(a + len(line) > b for a, b, line in
                   zip(positions[:-1], positions[1:], lines[:-1], strict=True))):
        return [citation]
    return [EvidenceCitation(evidenceId=citation.evidenceId, quote=line) for line in lines]


def ensure_citations(fact, sources, client, attempts, restore):
    checks, invalid = [], {}
    for key, value in fact.values.items():
        for citation in [value, *value.supportingEvidence]:
            source = sources.get(citation.evidenceId)
            if source is not None and citation.quote not in source.text:
                restored = restore(source, citation.quote)
                if restored is not None:
                    citation.quote = restored
                    checks.append({"code": "PDF_QUOTE_LINE_BREAKS_RESTORED",
                                   "field": f"facts.{key}", "ruleId": fact.ruleId,
                                   "evidenceId": citation.evidenceId})
            if source is None or citation.quote not in source.text:
                invalid[key] = value
    if not invalid:
        return checks
    prompt = Path(__file__).with_name("citation-repair-prompt.txt").read_text("utf-8")
    body = json.dumps({
        "values": {k: v.model_dump() for k, v in invalid.items()},
        "evidence": [s.model_dump() for s in sources.values()],
    }, ensure_ascii=False)
    for _ in range(attempts - 1):
        try:
            references = Repairs.model_validate(client.chat_json(prompt, body)).references
            if set(references) != set(invalid):
                raise ValueError("Repair field scope changed")
            # Validate typed copies; business text stays under program control.
            repaired = {key: type(invalid[key]).model_validate({
                **invalid[key].model_dump(), **ref.model_dump(),
            }) for key, ref in references.items()}
            for key, value in repaired.items():
                original = invalid[key]
                citations = [part for c in value.citations()
                             for part in split_pdf_citation(c, sources)]
                value.evidenceId, value.quote = citations[0].evidenceId, citations[0].quote
                value.supportingEvidence = citations[1:]
                for citation in value.citations():
                    source = sources.get(citation.evidenceId)
                    if source is None or citation.quote not in source.text:
                        raise ValueError("Repair is not a verbatim citation")
                good = [c for c in original.citations()
                        if c.evidenceId in sources and c.quote in sources[c.evidenceId].text]
                if any(c not in value.citations() for c in good):
                    raise ValueError("Repair cannot drop existing valid evidence")
            fact.values.update(repaired)
            checks.append({"code": "QUOTE_REFERENCES_REPAIRED", "ruleId": fact.ruleId,
                           "fields": sorted(repaired)})
            return checks
        except (ValueError, ValidationError, LLMError):
            continue
    raise ValueError("Model output references unknown evidence or non-verbatim quote")
