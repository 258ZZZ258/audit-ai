import json

from pipeline.supervision.evaluate import CLAIMS, PAIRS, evaluate


def test_evaluation_counts_failures_instead_of_reporting_only_successes():
    class Client:
        model = "deterministic-test"

        def chat_json(self, system, user):
            body = json.loads(user)
            if "claims" in body:
                return {"verdicts": [dict(id=key, supported=expected, reason="测试替身")
                                     for key, _, _, _, expected in CLAIMS]}
            return {"decisions": [dict(pairId=key, verdict="UNCERTAIN", reason="测试替身",
                                       issueQuote=issue, recordQuote=record)
                                  for key, issue, record, _ in PAIRS]}

    result = evaluate(Client())
    assert result["total"] == 11
    assert result["passed"] == 9
    assert len([case for case in result["cases"] if not case["passed"]]) == 2
