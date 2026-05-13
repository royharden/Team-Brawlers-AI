"""Rubric base model — master plan §8.3."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Rubric(BaseModel):
    """Boolean rubric definition consumed by the judge."""

    id: str
    description: str
    category: str
    success_indicators: list[str] = Field(default_factory=list)
    is_deterministic: bool = False


class RubricOutcome(BaseModel):
    """The result of running a single rubric check against an (attack, response) pair.

    Returned by every `check_<rubric_id>` function under `agentforge.judge.rubrics.*`.
    A `passed=True` outcome means the response respected the safety property the rubric
    encodes (i.e., the attack failed to achieve its goal for this dimension). A
    `passed=False` outcome means the attack succeeded against this rubric.

    `abstained=True` is reserved for the case where the rubric cannot make a
    deterministic call from the available evidence (e.g., the response carries no
    tool plan, and the rubric was about tool plans). The judge layer treats
    abstentions as "no signal" — neither a pass nor a fail — and they do NOT
    count against the success-rate metric.
    """

    passed: bool
    confidence: float = 1.0
    rationale: str = ""
    abstained: bool = False
