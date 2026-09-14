"""Offline labelled public-document benchmark. Gold never enters model requests.

Rubric coverage is deterministic, not a claim of semantic correctness. Source files
and annotations live outside the repository; paths are relative to the dataset.
"""

import argparse
import hashlib
import io
import json
import re
import time
from decimal import Decimal
from pathlib import Path

from common.ir import IRDocument, SourceFormat
from common.supervision import SupervisionExtractRequest
from pipeline.llm_client import make_llm_client
from pipeline.parsing.factory import make_ocr_parser
from pipeline.parsing.light_parser import LightParser
from pipeline.states import ErrorCode
from pipeline.supervision.extract import prepare_extraction
from pipeline.supervision.extraction_benchmark import metrics
from pipeline.supervision.prompting import load_prompt


def canonical(value):
    return re.sub(r"\s+", "", value).rstrip("。；")


def contains_term(value, term):
    term = canonical(term)
    # Only a well-formed thousands group permits a fullwidth separator.
    grouped = r"(?<![\d,，.])[+-]?\d{1,3}(?:，\d{3})+(?:\.\d+)?(?![\d,，.])"
    value = re.sub(grouped, lambda m: m[0].replace("，", ","), value)
    number = r"[+-]?\d+(?:,\d{3})*(?:\.\d+)?"
    if re.fullmatch(number, term):
        expected = Decimal(term.replace(",", ""))
        return any(
            Decimal(found.replace(",", "")) == expected for found in re.findall(number, value)
        )
    pattern = re.escape(term)
    if term and term[0].isdigit():
        pattern = r"(?<![\d.,])" + pattern
    if term and term[-1].isdigit():
        pattern += r"(?![\d.,])"
    return bool(term and re.search(pattern, value))


def satisfies(value, rubric):
    value = canonical(value)
    if not value:
        return False
    if "equals" in rubric:
        return value in [canonical(v) for v in rubric["equals"]]
    return all(
        any(contains_term(value, term) for term in alternatives) for alternatives in rubric["allOf"]
    ) and not any(contains_term(value, term) for term in rubric.get("noneOf", []))


def score_public(gold, predictions, evidence):
    """One-to-one matching; identity must occur in predicted values AND its quotes.

    Broad page text is deliberately never substituted for a prediction's quotes.
    Fields not in the gold are false positives (gold must cover all requested keys).
    """
    if len(gold) > 16:
        raise ValueError("At most 16 labelled records per evaluation case")
    quoted = []
    integrity = []
    for prediction in predictions:
        quotes = []
        valid = True
        for value in prediction["values"].values():
            for citation in [value, *value.get("supportingEvidence", [])]:
                source = evidence.get(citation.get("evidenceId"))
                ok = bool(source and citation.get("quote") and citation["quote"] in source["text"])
                integrity.append(ok)
                valid = valid and ok
                quotes.append(citation.get("quote", ""))
        quoted.append(("\n".join(quotes), valid and bool(quotes)))
    states = {0: (0, {})}
    for p, prediction in enumerate(predictions):
        text = "\n".join(v["value"] for v in prediction["values"].values())
        candidates = [
            g
            for g, expected in enumerate(gold)
            if prediction.get("factType") == expected["type"]
            and set(prediction["organizationIds"]) == set(expected["orgs"])
            and quoted[p][1]
            and satisfies(text, expected["identity"])
            and satisfies(quoted[p][0], expected["identity"])
        ]
        updated = dict(states)
        for mask, (count, owners) in states.items():
            for g in candidates:
                if mask & (1 << g):
                    continue
                correct = sum(
                    satisfies(prediction["values"].get(k, {}).get("value", ""), r)
                    for k, r in gold[g]["fields"].items()
                )
                new_mask = mask | (1 << g)
                if new_mask not in updated or count + correct > updated[new_mask][0]:
                    updated[new_mask] = (count + correct, {**owners, g: p})
        states = updated
    best = max(states, key=lambda mask: (mask.bit_count(), states[mask][0]))
    owners = states[best][1]
    details = []
    for g, expected in enumerate(gold):
        p = owners.get(g)
        values = predictions[p]["values"] if p is not None else {}
        details.append(
            {
                "goldId": expected["id"],
                "predictionIndex": p,
                "fields": {
                    k: {
                        "pass": satisfies(values.get(k, {}).get("value", ""), r),
                        "actual": values.get(k, {}).get("value"),
                        "rubric": r,
                    }
                    for k, r in expected["fields"].items()
                },
                "unexpectedFields": sorted(set(values) - set(expected["fields"])),
            }
        )
    correct = sum(f["pass"] for d in details for f in d["fields"].values())
    expected_count = sum(len(g["fields"]) for g in gold)
    predicted_count = sum(len(p["values"]) for p in predictions)
    return {
        "facts": metrics(len(owners), len(predictions) - len(owners), len(gold) - len(owners)),
        "fieldRubric": metrics(correct, predicted_count - correct, expected_count - correct),
        "citationIntegrity": {"valid": sum(integrity), "total": len(integrity)},
        "details": details,
        "unmatchedPredictions": [p for p in range(len(predictions)) if p not in owners.values()],
    }


def resolve_input(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Input file must be within dataset directory")
    return path


def parse_case(root, case):
    data = resolve_input(root, case["inputFile"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != case["inputSha256"]:
        raise ValueError("Input checksum mismatch")
    pages = case.get("pages")
    # Preserve PDF page geometry/content while limiting the declared evaluation scope.
    # Page labels are mapped back to original page numbers after production parsing.
    if pages:
        from pypdf import PdfReader, PdfWriter

        reader, writer = PdfReader(io.BytesIO(data)), PdfWriter()
        if len(set(pages)) != len(pages) or pages != sorted(pages):
            raise ValueError("Pages must be unique and ordered")
        for page in pages:
            if not 1 <= page <= len(reader.pages):
                raise ValueError("Invalid page scope")
            writer.add_page(reader.pages[page - 1])
        stream = io.BytesIO()
        writer.write(stream)
        data = stream.getvalue()
    parsed = LightParser().parse(data, case["format"], scanned_char_per_page_max=30)
    if parsed.error_code == ErrorCode.SCANNED_OCR_DISABLED.value:
        ocr = make_ocr_parser()
        if ocr is not None:
            parsed = ocr.parse(data, case["format"], scanned_char_per_page_max=30)
    if not parsed.ok:
        raise ValueError(parsed.error_code)
    if pages:
        for block in parsed.blocks:
            if block.page is not None:
                block.page = pages[block.page - 1]
            if block.page_end is not None:
                block.page_end = pages[block.page_end - 1]
    request = SupervisionExtractRequest.model_validate(case["request"])
    ir = IRDocument(
        doc_version_id=request.metadata.documentVersionId,
        source_format=SourceFormat(case["format"]),
        blocks=parsed.blocks,
        title=parsed.title,
    )
    return request, ir


class RecordingClient:
    def __init__(self, client):
        self.client = client
        self.calls = []

    def chat_json(self, system, user):
        call = {"system": system, "user": user}
        self.calls.append(call)
        try:
            response = self.client.chat_json(system, user)
            call["response"] = response
            return response
        except Exception as exc:
            call["error"] = type(exc).__name__
            raise


def run(dataset_path, output, client):
    raw = dataset_path.read_bytes()
    dataset = json.loads(raw)
    cases = dataset["cases"]
    if len({c["id"] for c in cases}) != len(cases):
        raise ValueError("Duplicate case id")
    groups = {}
    for case in cases:
        previous = groups.setdefault(case["sourceGroup"], case["split"])
        if previous != case["split"]:
            raise ValueError("Source group leaks across splits")
    result = {
        "datasetHash": hashlib.sha256(raw).hexdigest(),
        "dataset": dataset["id"],
        "scoringVersion": "public-identity-and-field-rubric.v1.2",
        "runnerHash": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "model": client.model,
        "coverageReview": True,
        "modelAttempts": 2,
        "maxEvidenceChars": 16000,
        "scope": dataset["scope"],
        "cases": [],
        "totalCases": len(cases),
        "promptHashes": {
            n: hashlib.sha256(load_prompt(n).encode("utf-8")).hexdigest()
            for n in ("extraction-prompt.txt", "coverage-prompt.txt")
        },
        "quoteRepairPromptHash": hashlib.sha256(
            Path(__file__).with_name("citation-repair-prompt.txt").read_bytes()
        ).hexdigest(),
    }
    with output.open("x", encoding="utf-8") as stream:
        for case in cases:
            started = time.monotonic()
            predictions, evidence, error, stage = [], {}, None, "parse"
            ir_json = None
            recording = RecordingClient(client)
            try:
                request, ir = parse_case(dataset_path.parent, case)
                ir_json = ir.model_dump(mode="json")
                stage = "extraction"
                extracted = prepare_extraction(
                    request,
                    ir,
                    client=recording,
                    max_evidence_chars=16000,
                    coverage_review=True,
                )
                predictions = extracted["facts"]
                evidence = {e["evidenceId"]: e for e in extracted["evidence"]}
            except Exception as exc:
                error = {"stage": stage, "type": type(exc).__name__}
            row = {
                "id": case["id"],
                "sourceGroup": case["sourceGroup"],
                "split": case["split"],
                "error": error,
                "seconds": round(time.monotonic() - started, 2),
                "predictions": predictions,
                "evidence": evidence,
                "ir": ir_json,
                "modelCalls": recording.calls,
                **score_public(case["gold"], predictions, evidence),
            }
            result["cases"].append(row)
            result["completed"] = len(result["cases"])
            result["failedCases"] = sum(r["error"] is not None for r in result["cases"])
            for metric in ("facts", "fieldRubric"):
                result[metric] = metrics(
                    *(sum(r[metric][k] for r in result["cases"]) for k in ("tp", "fp", "fn"))
                )
            stream.seek(0)
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.truncate()
            stream.flush()
            print(json.dumps({"id": case["id"], "error": error, "facts": row["facts"]}), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.dataset, args.output, make_llm_client(timeout=300, retries=1))
    raise SystemExit(1 if result["failedCases"] else 0)


if __name__ == "__main__":
    main()
