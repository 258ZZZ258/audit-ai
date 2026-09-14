"""Synthetic, source-anchored extraction benchmark with one-to-one scoring.

python -m pipeline.supervision.extraction_benchmark --output <new-json-path>
Gold labels never enter the model request. This measures extraction from IR, not OCR.
"""

import argparse
import hashlib
import json
import time
from pathlib import Path

from common.ir import Block, BlockType, IRDocument, SourceFormat
from common.supervision import SupervisionExtractRequest
from pipeline.llm_client import make_llm_client
from pipeline.supervision.extract import prepare_extraction


def dataset():
    specifications = [
        (
            "regulatory",
            "external.regulatory",
            "FINDING",
            "issueDescription",
            "离职人员权限未撤销",
            "客户风险等级未更新",
        ),
        (
            "external-audit",
            "external.audit",
            "FINDING",
            "issueDescription",
            "采购合同未审批",
            "费用报销附件缺失",
        ),
        (
            "internal-audit",
            "internal.audit",
            "FINDING",
            "issueDescription",
            "印章使用未登记",
            "固定资产盘点遗漏",
        ),
        (
            "compliance",
            "internal.compliance",
            "FINDING",
            "issueDescription",
            "适当性评估缺失",
            "营销材料未经审核",
        ),
        ("risk", "internal.risk", "FINDING", "issueDescription", "风险限额超限", "风险预警未处理"),
        (
            "accountability",
            "internal.accountability",
            "ACCOUNTABILITY",
            "accountabilityAction",
            "通报批评",
            "书面警告",
        ),
        (
            "daily-compliance",
            "internal.daily.compliance",
            "RECTIFICATION",
            "rectificationStatus",
            "部分完成",
            "未完成",
        ),
        (
            "daily-risk",
            "internal.daily.risk",
            "RECTIFICATION",
            "rectificationStatus",
            "进行中",
            "已完成",
        ),
        ("litigation", "internal.daily.litigation", "LITIGATION", "progress", "审理中", "执行中"),
    ]
    cases = []
    for name, section, kind, field, first, second in specifications:
        rows, gold = [], []
        for i, value in enumerate((first, second)):
            org, label = ("ORG-A", "甲单位") if i == 0 else ("ORG-B", "乙单位")
            anchor = f"事项{['甲', '乙'][i]}"
            prefix = {
                "FINDING": "检查新发现问题",
                "RECTIFICATION": "历史问题整改进展",
                "ACCOUNTABILITY": "问责处理决定",
                "LITIGATION": "诉讼案件进展",
            }[kind]
            rows.append(f"{label}{anchor}：{prefix}。{field}：{value}。")
            gold.append({"type": kind, "org": org, "anchor": anchor, "fields": {field: value}})
        cases.append({"id": name, "section": section, "field": field, "rows": rows, "gold": gold})
    cases.extend(
        [
            {
                "id": "no-findings-background",
                "section": "external.regulatory",
                "field": "issueDescription",
                "rows": ["甲单位成立于2010年。本文仅介绍机构背景，不记载检查发现。"],
                "gold": [],
            },
            {
                "id": "no-material-not-no-problem",
                "section": "internal.daily.risk",
                "field": "issueDescription",
                "rows": ["甲单位本月风险监督资料尚未报送，不能判断是否存在问题。"],
                "gold": [],
            },
            {
                "id": "followup-not-new-finding",
                "section": "internal.audit",
                "field": "rectificationStatus",
                "rows": [
                    "甲单位事项甲：历史问题为离职权限未撤销，本次仅汇报整改进展，整改状态：部分完成。"
                ],
                "gold": [
                    {
                        "type": "RECTIFICATION",
                        "org": "ORG-A",
                        "anchor": "事项甲",
                        "fields": {"rectificationStatus": "部分完成"},
                    }
                ],
            },
        ]
    )
    return cases


def inputs(case):
    request = SupervisionExtractRequest.model_validate(
        {
            "metadata": {
                "documentId": "DOC",
                "documentVersionId": "DV",
                "fileName": "评测资料.docx",
                "issueDate": "2026-06-30",
                "categoryCode": case["id"],
                "documentOrigin": "internal",
                "organizationIds": ["ORG-A", "ORG-B"],
                "uploadEntry": "supervision",
            },
            "organizations": [
                {"organizationId": "ORG-A", "name": "甲单位"},
                {"organizationId": "ORG-B", "name": "乙单位"},
            ],
            "rules": [
                {
                    "ruleId": case["id"],
                    "reportSection": case["section"],
                    "extractFields": [
                        {
                            "key": case["field"],
                            "description": "按原文提取该业务字段，不创造信息",
                            "required": True,
                        },
                    ],
                }
            ],
        }
    )
    ir = IRDocument(
        doc_version_id="DV",
        source_format=SourceFormat.DOCX,
        blocks=[
            Block(index=i, type=BlockType.PARAGRAPH, text=row) for i, row in enumerate(case["rows"])
        ],
    )
    return request, ir


def challenge_dataset():
    definitions = [
        (
            "same-org-two-records",
            "internal.risk",
            "rectificationStatus",
            "RECTIFICATION",
            [
                "甲单位权限整改事项甲已全部完成；合同整改事项乙目前只完成了部分，仍在推进。",
            ],
            [("事项甲", "已完成"), ("事项乙", "部分完成")],
        ),
        (
            "same-case-two-months",
            "internal.daily.litigation",
            "progress",
            "LITIGATION",
            [
                "甲单位案件（2026）沪01号：三月快照记载尚在审理中。",
                "甲单位同一案件（2026）沪01号：六月快照记载已进入执行阶段，执行中。",
            ],
            [("三月快照", "审理中"), ("六月快照", "执行中")],
        ),
        (
            "natural-two-findings",
            "internal.audit",
            "issueDescription",
            "FINDING",
            [
                "检查甲单位时发现两项独立问题：事项甲，离职人员仍能登录交易系统；事项乙，采购合同未履行审批手续。",
            ],
            [("事项甲", "离职人员仍能登录交易系统"), ("事项乙", "采购合同未履行审批手续")],
        ),
        (
            "dispersed-progress",
            "internal.risk",
            "rectificationMeasure",
            "RECTIFICATION",
            [
                "甲单位事项甲是离职权限整改：本次已注销全部离职账号。",
                "上述事项甲同时完成了账号清理结果复核，本次措施为注销离职账号并完成复核。",
            ],
            [("事项甲", "注销离职账号并完成复核")],
        ),
        (
            "actual-vs-budget",
            "external.audit",
            "amount",
            "FINDING",
            [
                "甲单位事项甲涉及违规报销10万元。项目预算100万元不属于问题金额。",
            ],
            [("事项甲", "10万元")],
        ),
        (
            "policy-not-finding",
            "internal.compliance",
            "issueDescription",
            "FINDING",
            [
                "制度要求甲单位发现异常时及时报告。这是制度培训材料，未记载实际异常或检查问题。",
            ],
            [],
        ),
    ]
    return [
        {
            "id": name,
            "section": section,
            "field": field,
            "rows": rows,
            "gold": [
                {"type": kind, "org": "ORG-A", "anchor": anchor, "fields": {field: value}}
                for anchor, value in labels
            ],
        }
        for name, section, field, kind, rows, labels in definitions
    ]


def metrics(tp, fp, fn):
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
    }


def score(gold, predictions, evidence=None):
    # Maximum one-to-one matching. A duplicate prediction can never raise recall above 1.
    edges = []
    for prediction in predictions:
        quotes = "\n".join(
            (evidence or {}).get(c["evidenceId"], c["quote"])
            for v in prediction["values"].values()
            for c in [v, *v.get("supportingEvidence", [])]
        )
        edges.append(
            [
                i
                for i, expected in enumerate(gold)
                if prediction.get("factType") == expected["type"]
                and set(prediction["organizationIds"]) == {expected["org"]}
                and expected["anchor"] in quotes
            ]
        )
    # Small fixed cases: maximize matched items, then exact fields, independent of order.
    if len(gold) > 16:
        raise ValueError("Split benchmark cases into at most 16 gold items")
    states = {0: (0, {})}
    for p, candidates in enumerate(edges):
        updated = dict(states)
        for mask, (correct, assigned) in states.items():
            for g in candidates:
                if mask & (1 << g):
                    continue
                count = sum(
                    predictions[p]["values"].get(k, {}).get("value", "").strip() == v
                    for k, v in gold[g]["fields"].items()
                )
                new_mask = mask | (1 << g)
                if new_mask not in updated or correct + count > updated[new_mask][0]:
                    updated[new_mask] = (correct + count, {**assigned, g: p})
        states = updated
    best = max(states, key=lambda mask: (mask.bit_count(), states[mask][0]))
    owners = states[best][1]
    field_tp = sum(
        predictions[p]["values"].get(key, {}).get("value", "").strip() == value
        for g, p in owners.items()
        for key, value in gold[g]["fields"].items()
    )
    normalized_tp = sum(
        predictions[p]["values"].get(key, {}).get("value", "").strip().rstrip("。；")
        == value.strip().rstrip("。；")
        for g, p in owners.items()
        for key, value in gold[g]["fields"].items()
    )
    predicted_fields = sum(len(p["values"]) for p in predictions)
    gold_fields = sum(len(g["fields"]) for g in gold)
    return {
        "facts": metrics(len(owners), len(predictions) - len(owners), len(gold) - len(owners)),
        "fields": metrics(field_tp, predicted_fields - field_tp, gold_fields - field_tp),
        "normalizedFields": metrics(
            normalized_tp, predicted_fields - normalized_tp, gold_fields - normalized_tp
        ),
        "unmatchedGold": [i for i in range(len(gold)) if i not in owners],
        "unmatchedPredictions": [i for i in range(len(predictions)) if i not in owners.values()],
    }


def run(client, output, coverage=True, suite="all"):
    cases = (dataset() if suite in ("basic", "all") else []) + (
        challenge_dataset() if suite in ("challenge", "all") else []
    )
    result = {
        "dataset": "synthetic-extraction-pr.v1",
        "datasetHash": hashlib.sha256(
            json.dumps(cases, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest(),
        "model": client.model,
        "coverageReview": coverage,
        "suite": suite,
        "scoringVersion": "source-anchor-exact-fields.v1",
        "promptHashes": {
            name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ("extraction-prompt.txt", "coverage-prompt.txt")
        },
        "cases": [],
    }
    # A new result is required; checkpoints include failures and never silently skip a case.
    with output.open("x", encoding="utf-8") as stream:
        for case in cases:
            start = time.monotonic()
            request, ir = inputs(case)
            try:
                extracted = prepare_extraction(
                    request, ir, client=client, max_evidence_chars=16000, coverage_review=coverage
                )
                predictions = extracted["facts"]
                evidence = {e["evidenceId"]: e["text"] for e in extracted["evidence"]}
                error = None
            except Exception as exc:
                predictions, evidence, error = [], {}, type(exc).__name__
            row = {
                "id": case["id"],
                "gold": case["gold"],
                "predictions": predictions,
                "error": error,
                "seconds": round(time.monotonic() - start, 2),
                "evidence": evidence,
                **score(case["gold"], predictions, evidence),
            }
            result["cases"].append(row)
            result["completed"] = len(result["cases"])
            result["totalCases"] = len(cases)
            result["failedCases"] = sum(c["error"] is not None for c in result["cases"])
            for level in ("facts", "fields", "normalizedFields"):
                result[level] = metrics(
                    *(sum(c[level][k] for c in result["cases"]) for k in ("tp", "fp", "fn"))
                )
            stream.seek(0)
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.truncate()
            stream.flush()
            print(json.dumps({"id": row["id"], "error": error, "facts": row["facts"]}), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--no-coverage", action="store_true")
    parser.add_argument("--suite", choices=["basic", "challenge", "all"], default="all")
    args = parser.parse_args()
    result = run(
        make_llm_client(timeout=300, retries=1), args.output, not args.no_coverage, args.suite
    )
    raise SystemExit(1 if result["failedCases"] else 0)


if __name__ == "__main__":
    main()
