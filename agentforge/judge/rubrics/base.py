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
