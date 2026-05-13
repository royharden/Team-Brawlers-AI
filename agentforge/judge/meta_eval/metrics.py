"""Judge meta-eval metrics — master plan §10. Stub."""

from __future__ import annotations

from pydantic import BaseModel


class JudgeMetaEvalResult(BaseModel):
    """Precision / recall / F1 / Krippendorff alpha for one gold-set version."""

    gold_set_version: str
    precision: float
    recall: float
    f1: float
    krippendorff_alpha: float
