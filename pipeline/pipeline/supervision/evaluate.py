"""Small synthetic regression set; never reported as real-document extraction accuracy.

Run: python -m pipeline.supervision.evaluate --output <new-json-path>
Uses the configured real gateway; refuses to overwrite an existing result.
"""

import argparse
import json
from pathlib import Path

from pipeline.llm_client import make_llm_client
from pipeline.supervision.association import AssociationRequest, judge_pairs
from pipeline.supervision.verification import VerificationRequest, verify_claims

CLAIMS = [
    ("regulatory", "issueDescription", "适当性管理不到位", "监管函指出适当性管理不到位。", True),
    ("external-audit", "amount", "100万元", "审计报告列示金额10万元。", False),
    ("internal-audit", "organization", "乙公司", "检查发现甲公司未及时回收离职权限。", False),
    ("compliance", "rectificationStatus", "已完成", "合规整改尚未完成。", False),
    ("risk", "rectificationStatus", "全部完成", "风险事项中两项完成，其余仍在整改。", False),
    ("accountability", "accountabilityAction", "通报批评", "决定对相关责任人通报批评。", True),
    ("routine", "issueDescription", "未发现异常", "本月日常监督资料尚未报送。", False),
    ("litigation", "progress", "已执行完毕", "案件已判决，尚未执行完毕。", False),
]

PAIRS = [
    ("same-matter", "离职人员交易系统权限未及时撤销", "已注销离职人员交易系统账号", "MATCH"),
    ("other-matter", "离职人员交易系统权限未及时撤销", "采购合同审批手续已经补齐", "NO_MATCH"),
    ("vague", "离职人员交易系统权限未及时撤销", "相关问题正在逐步整改", "UNCERTAIN"),
]


def evaluate(client):
    claims = VerificationRequest(claims=[
        dict(id=key, field=field, value=value, evidence=evidence)
        for key, field, value, evidence, _ in CLAIMS
    ])
    verification = verify_claims(claims, client)
    actual = {row["id"]: row["supported"] for row in verification["verdicts"]}
    rows = [{"id": key, "expected": expected, "actual": actual[key],
             "passed": actual[key] == expected} for key, _, _, _, expected in CLAIMS]
    pairs = AssociationRequest(pairs=[
        dict(pairId=key, issueText=issue, recordText=record) for key, issue, record, _ in PAIRS
    ])
    decisions = judge_pairs(pairs, client)
    actual = {row["pairId"]: row["verdict"] for row in decisions["decisions"]}
    rows.extend({"id": key, "expected": expected, "actual": actual[key],
                 "passed": actual[key] == expected} for key, _, _, expected in PAIRS)
    return {"dataset": "synthetic-supervision-boundaries.v1", "model": client.model,
            "total": len(rows), "passed": sum(row["passed"] for row in rows), "cases": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    # Reserve output before paid calls; failures leave no misleading success result.
    with args.output.open("x", encoding="utf-8") as output:
        result = evaluate(make_llm_client(timeout=300, retries=1))
        json.dump(result, output, ensure_ascii=False, indent=2)
    print(json.dumps({"total": result["total"], "passed": result["passed"]}))
    raise SystemExit(0 if result["total"] == result["passed"] else 1)


if __name__ == "__main__":
    main()
