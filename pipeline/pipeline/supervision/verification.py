"""Verify extracted claims against full supplied evidence context."""

import re

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from pipeline.supervision.prompting import load_prompt


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=200)
    field: str = Field(min_length=1, max_length=200)
    value: str = Field(min_length=1, max_length=4000)
    evidence: str = Field(min_length=1, max_length=32000)


class VerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claims: list[Claim] = Field(min_length=1, max_length=8)


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    supported: StrictBool
    reason: str = Field(min_length=1, max_length=1000)


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verdicts: list[Verdict]


def verify_claims(body: VerificationRequest, client):
    expected = {claim.id for claim in body.claims}
    if len(expected) != len(body.claims):
        raise ValueError("Duplicate claim ID")
    prompt = load_prompt("verification-prompt.txt")
    for attempt in range(2):
        result = VerificationResult.model_validate(client.chat_json(prompt, body.model_dump_json()))
        if len(result.verdicts) != len(expected) or {v.id for v in result.verdicts} != expected:
            if attempt:
                raise ValueError("Incomplete or invalid verification")
            prompt += "\n前次输出漏掉、重复或修改了输入ID。重新核对原始输入，恰好返回每个ID一次。"
            continue
        # Only recognize an explicit negative conclusion, not arbitrary negation
        # in source descriptions (e.g. '未完成' may validly support that status).
        contradictory = [v.id for v in result.verdicts if v.supported and re.search(
            r"(?:故|因此|所以|结论[为是：:]|应判[为：:]?)\s*"
            r"(?:不支持|false|不能支持|无法支持)", v.reason, re.IGNORECASE,
        )]
        if not contradictory:
            return result.model_dump()
        if attempt:
            raise ValueError("Contradictory verification decision and reason")
        prompt += ("\n前次输出存在理由明确判不支持但supported为true的矛盾。"
                   "重新逐条核对原始证据并返回所有ID，理由与布尔结论必须一致。")
