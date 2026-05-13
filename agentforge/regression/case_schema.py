"""Regression case Pydantic model — master plan §13. Mirrors evals/regression/VR-####.json."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class RegressionCase(BaseModel):
    """One regression case = one confirmed exploit replay."""

    vr_id: str
    category: str
    target_endpoint: str
    rendered_prompt: str
    rendered_document: dict[str, Any] | None = None
    expected_safe_behavior: str
    what_bug_this_catches: str
    severity: str = "Medium"
    references: list[str] = Field(default_factory=list)

    @field_validator("what_bug_this_catches")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("what_bug_this_catches must be non-empty (master plan §13)")
        return v
