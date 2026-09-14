"""完整 IR 证据 → 有逐字摘录的字段候选；不改上传元数据，不确认业务事实。"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Protocol

from pydantic import ValidationError

from common.ir import BlockType, IRDocument, SourceFormat
from common.supervision import ModelFacts, SupervisionEvidence, SupervisionExtractRequest
from pipeline.llm_client import LLMError
from pipeline.meta import l1_rules
from pipeline.supervision.coverage import group_evidence, review_coverage
from pipeline.supervision.normalization import normalize_status
from pipeline.supervision.prompting import load_prompt
from pipeline.supervision.quote_repair import ensure_citations


class JsonExtractor(Protocol):
    def chat_json(self, system: str, user: str) -> dict: ...


def _restore_pdf_line_breaks(source: SupervisionEvidence, quote: str) -> str | None:
    """仅恢复 PDF 排版换行：其他字符（包括空格）必须一致且只能命中一处。"""
    if source.locatorType != "PAGE_TEXT":
        return None
    positions = [i for i, char in enumerate(source.text) if char not in "\r\n"]
    text = "".join(source.text[i] for i in positions)
    needle = quote.replace("\r", "").replace("\n", "")
    if not needle:
        return None
    start = text.find(needle)
    if start < 0 or text.find(needle, start + 1) >= 0:
        return None
    return source.text[positions[start]:positions[start + len(needle) - 1] + 1]


def evidence_from_ir(request: SupervisionExtractRequest, ir: IRDocument):
    meta = request.metadata
    if ir.doc_version_id != meta.documentVersionId:
        raise ValueError("IR document version does not match upload metadata")
    evidence: list[SupervisionEvidence] = []
    blocks = iter(ir.blocks)
    pending = next(blocks, None)
    while pending is not None:
        block = pending
        pending = next(blocks, None)
        if block.type == BlockType.TABLE:
            table = block.table
            if not (0 <= table.header_rows <= table.n_rows) or any(
                c.row < 0
                or c.col < 0
                or c.rowspan < 1
                or c.colspan < 1
                or c.row + c.rowspan > table.n_rows
                or c.col + c.colspan > table.n_cols
                for c in table.cells
            ):
                raise ValueError("Invalid IR table bounds; refusing incomplete row extraction")
            rows = table.expanded_rows()
            headers = rows[: table.header_rows]
            entries = [
                (
                    f"block:{block.index}:row:{i}",
                    "TABLE_ROW",
                    json.dumps(
                        {"headers": headers, "row": row},
                        ensure_ascii=False,
                    ),
                )
                for i, row in enumerate(rows)
                if i >= table.header_rows
            ]
            # 只有表头的表格也保留，不能丢失原文。
            if not entries:
                entries = [(f"block:{block.index}:row:0", "TABLE_ROW", table.to_markdown())]
        elif (
            ir.source_format == SourceFormat.PDF
            and block.type == BlockType.PARAGRAPH
            and block.page is not None
            and block.page_end in (None, block.page)
            and block.bbox is None
            and block.ocr_conf is None
        ):
            # LightParser 的 PDF block 是排版行。按同页连续文本构造引用窗口，
            # 保留换行与原 block 范围，不修改 IR，不跨表格/标题/OCR 布局块。
            run = [block]
            while (
                pending is not None
                and pending.type == BlockType.PARAGRAPH
                and pending.page == block.page
                and pending.page_end in (None, block.page)
                and pending.bbox is None
                and pending.ocr_conf is None
            ):
                run.append(pending)
                pending = next(blocks, None)
            if len(run) == 1:
                entries = [(f"block:{block.index}", "PARAGRAPH", block.text)]
            else:
                entries = [(
                    f"blocks:{block.index}-{run[-1].index}", "PAGE_TEXT",
                    "\n".join(b.text for b in run),
                )]
        else:
            entries = [(f"block:{block.index}", "PARAGRAPH", block.text)]
        for locator, kind, text in entries:
            if not text.strip():
                continue
            # 内容摘要纳入编号，使同版本人工 IR 修复后旧候选不会复用旧证据号。
            digest = hashlib.sha256(text.encode()).hexdigest()[:16]
            evidence.append(
                SupervisionEvidence(
                    evidenceId=f"{meta.documentVersionId}:{locator}:{digest}",
                    documentId=meta.documentId,
                    documentVersionId=meta.documentVersionId,
                    locatorType=kind,
                    locatorValue=locator,
                    pageStart=block.page,
                    pageEnd=block.page_end or block.page,
                    text=text,
                )
            )
    return evidence


def prepare_extraction(
    request: SupervisionExtractRequest,
    ir: IRDocument,
    *,
    client: JsonExtractor | None,
    max_evidence_chars: int,
    model_attempts: int = 2,
    coverage_review: bool = False,
) -> dict:
    if not 1 <= model_attempts <= 3:
        raise ValueError("model_attempts must be between 1 and 3")
    evidence = evidence_from_ir(request, ir)
    if not evidence:
        raise ValueError("No usable supervision evidence in IR")
    detected = l1_rules.extract(ir, [])
    checks = []
    if request.metadata.title and detected.title:
        if request.metadata.title.strip() != detected.title.strip():
            checks.append(
                {"field": "title", "code": "TITLE_DIFFERENCE", "candidate": detected.title}
            )
    if not request.metadata.issueDate:
        checks.append({"field": "issueDate", "code": "MISSING_ISSUE_DATE"})
    else:
        try:
            supplied = date.fromisoformat(request.metadata.issueDate)
            if supplied.isoformat() != request.metadata.issueDate:
                raise ValueError("non-canonical date")
        except ValueError:
            checks.append({"field": "issueDate", "code": "INVALID_ISSUE_DATE"})
        else:
            if detected.dates and supplied not in detected.dates:
                checks.append({"field": "issueDate", "code": "DATE_NOT_FOUND_IN_TEXT"})
    # 所有日期只作候选，不能推断最后出现的日期就是发文日期。
    checks.append({"field": "dateCandidates", "candidates": [str(d) for d in detected.dates]})
    facts: list[dict] = []
    if client is not None:
        prompt = load_prompt("extraction-prompt.txt")
        groups = group_evidence(evidence, max_evidence_chars)
        rules = {r.ruleId: r for r in request.rules}
        batches = []
        for group_index, group in enumerate(groups):
            sources = {e.evidenceId: e for e in group}
            body = {
                "metadata": request.metadata.model_dump(),
                "organizations": [o.model_dump() for o in request.organizations],
                "rules": [
                    {
                        **r.model_dump(),
                        "extractFields": [
                            f.model_dump() for f in r.extractFields if f.key != "evidenceLocation"
                        ],
                    }
                    for r in request.rules
                ],
                "evidence": [e.model_dump() for e in group],
            }
            for attempt in range(model_attempts):
                try:
                    retry_note = "" if attempt == 0 else (
                        "\n上次输出未通过格式校验，请从相同原文重新完整提取。"
                        "每个业务字段必须同时包含字符串 value、evidenceId、quote。"
                        "不得省略 value，不得用 quote 代替 value；facts 必须是数组，"
                        "检查 JSON 括号和引号闭合。"
                    )
                    response = ModelFacts.model_validate(client.chat_json(
                        prompt + retry_note, json.dumps(body, ensure_ascii=False)
                    ))
                    break
                except (LLMError, ValidationError):
                    if attempt + 1 == model_attempts:
                        raise
                    checks.append({"code": "MODEL_OUTPUT_RETRY", "attempt": attempt + 2})
            if coverage_review:
                for attempt in range(model_attempts):
                    try:
                        response, review_check = review_coverage(
                            body, response, client, retry=attempt > 0,
                        )
                        checks.append({**review_check, "groupIndex": group_index})
                        break
                    except (LLMError, ValidationError):
                        if attempt + 1 == model_attempts:
                            raise
                        checks.append({"code": "COVERAGE_OUTPUT_RETRY", "attempt": attempt + 2})
            batches.append((sources, response))
        if coverage_review:
            for index in range(1, len(groups)):
                boundary = [groups[index - 1][-1], groups[index][0]]
                if sum(len(e.text) for e in boundary) > max_evidence_chars:
                    checks.append({"code": "BOUNDARY_REVIEW_SKIPPED_CAPACITY", "groupIndex": index})
                    continue
                boundary_ids = {e.evidenceId for e in boundary}
                targets = []
                for batch_index in (index - 1, index):
                    for fact_index, fact in enumerate(batches[batch_index][1].facts):
                        cited = {c.evidenceId for v in fact.values.values() for c in v.citations()}
                        if cited and cited <= boundary_ids:
                            targets.append((batch_index, fact_index, fact))
                if not targets:
                    checks.append({
                        "code": "BOUNDARY_REVIEW_NO_COMPLETE_TARGET", "groupIndex": index,
                    })
                    continue
                boundary_body = {**body, "evidence": [e.model_dump() for e in boundary],
                                 "boundaryOnly": True}
                reviewed, check = review_coverage(
                    boundary_body, ModelFacts(facts=[t[2] for t in targets]), client,
                )
                # Only supplement known facts; new boundary facts could duplicate group output.
                if len(reviewed.facts) != len(targets):
                    raise ValueError("Boundary review cannot add independent facts")
                for target, updated in zip(targets, reviewed.facts, strict=True):
                    batch_index, fact_index, _ = target
                    batches[batch_index][1].facts[fact_index] = updated
                    batches[batch_index][0].update({e.evidenceId: e for e in boundary})
                checks.append({**check, "code": "BOUNDARY_REVIEWED", "groupIndex": index})
        for sources, response in batches:
            for fact in response.facts:
                if fact.ruleId not in rules:
                    raise ValueError("Unknown extraction rule in model output")
                if not set(fact.organizationIds) <= set(request.metadata.organizationIds):
                    raise ValueError("Model output organization outside uploaded scope")
                allowed_fields = {f.key for f in rules[fact.ruleId].extractFields}
                if (fact.factType == "ACCOUNTABILITY"
                        and rules[fact.ruleId].reportSection != "internal.accountability"
                        and allowed_fields <= {
                            "issueDescription", "rectificationStatus", "evidenceLocation",
                        }):
                    checks.append({"code": "ACCOUNTABILITY_OUTSIDE_REQUESTED_FIELDS",
                                   "ruleId": fact.ruleId})
                    continue
                if not set(fact.values) <= allowed_fields:
                    raise ValueError("Unknown extraction field in model output")
                checks.extend(ensure_citations(
                    fact, sources, client, model_attempts, _restore_pdf_line_breaks,
                ))
                payload = fact.model_dump(exclude_defaults=True)
                # Keep the wire type explicit even for legacy clients omitting it.
                # An unknown type must not silently become a new finding.
                payload["factType"] = fact.factType
                if (fact.factType == "UNSPECIFIED"
                        and rules[fact.ruleId].reportSection == "internal.accountability"
                        and "accountabilityAction" in fact.values):
                    payload["factType"] = "ACCOUNTABILITY"
                    checks.append({"code": "FACT_TYPE_FROM_ACCOUNTABILITY_RULE",
                                   "ruleId": fact.ruleId})
                if (fact.factType == "UNSPECIFIED"
                        and rules[fact.ruleId].reportSection == "internal.daily.litigation"):
                    payload["factType"] = "LITIGATION"
                    checks.append({"code": "FACT_TYPE_FROM_LITIGATION_RULE", "ruleId": fact.ruleId})
                if "rectificationStatus" in payload["values"]:
                    status = payload["values"]["rectificationStatus"]
                    normalized = normalize_status(status["value"])
                    if normalized != status["value"]:
                        checks.append({"code": "STATUS_NORMALIZED", "ruleId": fact.ruleId,
                                       "originalValue": status["value"], "value": normalized})
                        status["value"] = normalized
                if "evidenceLocation" in allowed_fields:
                    # 定位来自已校验的证据元数据，不让模型猜页码或块范围。
                    first_value = next(iter(fact.values.values()))
                    all_citations = [
                        citation for value in fact.values.values() for citation in value.citations()
                    ]
                    cited = list(dict.fromkeys(c.evidenceId for c in all_citations))
                    locations = []
                    for evidence_id in cited:
                        source = sources[evidence_id]
                        page = f"第{source.pageStart}页；" if source.pageStart else ""
                        if source.pageStart and source.pageEnd != source.pageStart:
                            page = f"第{source.pageStart}-{source.pageEnd}页；"
                        locations.append(f"{page}{source.locatorValue}")
                    payload["values"]["evidenceLocation"] = {
                        "value": " / ".join(locations),
                        "evidenceId": first_value.evidenceId,
                        "quote": first_value.quote,
                    }
                    # 派生定位也保留完整回溯入口；去重不改变任何业务字段的引用。
                    unique_citations = {
                        (c.evidenceId, c.quote): c.model_dump() for c in all_citations
                    }
                    unique_citations.pop((first_value.evidenceId, first_value.quote), None)
                    if unique_citations and any(v.supportingEvidence for v in fact.values.values()):
                        payload["values"]["evidenceLocation"]["supportingEvidence"] = list(
                            unique_citations.values()
                        )
                hash_payload = dict(payload)
                if hash_payload.get("factType") == "UNSPECIFIED":
                    # Preserve legacy identities: the old default was omitted from
                    # hashing. The response can still expose the default explicitly.
                    hash_payload.pop("factType")
                canonical = json.dumps(hash_payload, ensure_ascii=False, sort_keys=True)
                facts.append(
                    {
                        "factId": hashlib.sha256(canonical.encode()).hexdigest(),
                        "reportSection": rules[fact.ruleId].reportSection,
                        "confirmationStatus": "PENDING_REVIEW",
                        "missingRequiredFields": [
                            f.key
                            for f in rules[fact.ruleId].extractFields
                            if f.required and f.key not in payload["values"]
                        ],
                        **payload,
                    }
                )
    # 同一证据重复返回只保留一份；不同资料/行的同文事实不在此强行合并。
    unique = {f["factId"]: f for f in facts}
    return {
        "schemaVersion": "supervision-extraction.v1",
        "extractionStatus": "EXTRACTED" if client is not None else "EVIDENCE_READY",
        "metadataChecks": checks,
        "evidence": [e.model_dump() for e in evidence],
        "facts": list(unique.values()),
    }
