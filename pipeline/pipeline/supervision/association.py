"""有证据摘录的逐项关联判定；不推断整改完成状态。"""
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from pipeline.supervision.similarity import SimilarityPair


class AssociationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pairs: list[SimilarityPair] = Field(min_length=1, max_length=8)


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pairId: str
    verdict: Literal["MATCH", "NO_MATCH", "UNCERTAIN"]
    reason: str = Field(min_length=1, max_length=1000)
    issueQuote: str = Field(min_length=1, max_length=4000)
    recordQuote: str = Field(min_length=1, max_length=4000)


class Decisions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decisions: list[Decision]


def judge_pairs(request: AssociationRequest, client):
    pairs = {p.pairId: p for p in request.pairs}
    if len(pairs) != len(request.pairs):
        raise ValueError("Duplicate pair IDs")
    prompt = Path(__file__).with_name("association-prompt.txt").read_text("utf-8")
    result = Decisions.model_validate(client.chat_json(prompt, request.model_dump_json()))
    if len(result.decisions) != len(pairs) or {d.pairId for d in result.decisions} != set(pairs):
        raise ValueError("Decision coverage mismatch")
    for decision in result.decisions:
        pair = pairs[decision.pairId]
        if not decision.issueQuote.strip() or decision.issueQuote not in pair.issueText:
            raise ValueError("Invalid issue quote")
        if not decision.recordQuote.strip() or decision.recordQuote not in pair.recordText:
            raise ValueError("Invalid record quote")
    return json.loads(result.model_dump_json())
