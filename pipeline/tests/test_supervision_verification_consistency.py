import pytest

from pipeline.supervision.verification import VerificationRequest, verify_claims


class Client:
    def __init__(self, verdicts):
        self.verdicts = iter(verdicts)
        self.calls = 0

    def chat_json(self, system, user):
        self.calls += 1
        supported, reason = next(self.verdicts)
        return {"verdicts": [{"id": "one", "supported": supported, "reason": reason}]}


def request():
    return VerificationRequest(claims=[{
        "id": "one", "field": "rectificationStatus", "value": "已完成",
        "evidence": "3处房产已收回2处，剩余1处尚未收回。",
    }])


def test_explicit_contradiction_retries_instead_of_approving():
    client = Client([(True, "剩余尚未收回，故不支持。"), (False, "尚未全部收回。")])
    assert verify_claims(request(), client)["verdicts"][0]["supported"] is False
    assert client.calls == 2


def test_persistent_contradiction_fails_closed():
    client = Client([(True, "因此不支持。"), (True, "所以不能支持。")])
    with pytest.raises(ValueError, match="Contradictory"):
        verify_claims(request(), client)
    assert client.calls == 2


def test_negation_in_business_evidence_does_not_invert_verdict():
    client = Client([(True, "原文明确未完成，支持该未完成状态。")])
    body = request()
    body.claims[0].value = "未完成"
    assert verify_claims(body, client)["verdicts"][0]["supported"] is True
    assert client.calls == 1


@pytest.mark.parametrize("recover", [True, False])
def test_missing_verdict_retries_but_never_returns_incomplete_result(recover):
    class MissingClient:
        calls = 0

        def chat_json(self, system, user):
            self.calls += 1
            if recover and self.calls == 2:
                return {"verdicts": [{"id": "one", "supported": False, "reason": "尚未全部收回"}]}
            return {"verdicts": []}

    client = MissingClient()
    if recover:
        assert verify_claims(request(), client)["verdicts"][0]["supported"] is False
    else:
        with pytest.raises(ValueError, match="Incomplete"):
            verify_claims(request(), client)
    assert client.calls == 2
