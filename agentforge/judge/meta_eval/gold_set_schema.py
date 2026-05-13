"""Gold-set schema for judge meta-eval — master plan §10 / §22 (DoD 16).

A ``GoldCase`` is one hand-labeled (attack_prompt, target_response, expected_label)
triple used to validate the External Final Judge. The case_id is opaque; the
``category`` + ``rubric_focus`` determine which judge call path is exercised.

A ``GoldSet`` is a versioned collection of cases with provenance metadata. Cases
are persisted as JSONL: the first line is a header dict (``cases_follow: true``)
and every subsequent line is one ``GoldCase`` JSON object.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


class GoldCase(BaseModel):
    """One hand-labeled judge-validation case.

    The judge MUST emit the same verdict as ``expected_label`` for the case
    to count as a correct judge. The ``case_id`` is opaque; the ``category`` +
    ``rubric_focus`` determine which judge call path is exercised.
    """

    case_id: str
    category: str
    rubric_focus: str
    attack_prompt: str
    target_response: str
    expected_safe_behavior: str
    expected_label: Literal["passed", "failed"]
    expected_failed_rubrics: list[str] = Field(default_factory=list)
    label_rationale: str = Field(min_length=10)
    is_adversarial_against_judge: bool = False
    # Optional structured-response carrier for rubrics that inspect tool plans
    # or other non-text response fields (data lands in AdapterResponse.body_json
    # so the judge's _coerce_response can surface tool_plan / tool_calls /
    # legitimate_tool_plan into the deterministic check functions).
    target_body_json: dict | None = None
    notes: str | None = None
    references: list[str] = Field(default_factory=list)


class GoldSet(BaseModel):
    """v1 gold set with provenance metadata."""

    version: str
    created_at: datetime
    n_cases: int
    cases: list[GoldCase]
    label_provenance: str

    # ------------------------------------------------------------------
    # JSONL persistence
    # ------------------------------------------------------------------

    @classmethod
    def from_jsonl(cls, path: Path) -> GoldSet:
        """Load a GoldSet from a JSONL file.

        Layout:
          line 1: header JSON object with ``version``, ``created_at``,
                  ``n_cases``, ``label_provenance``, ``cases_follow: true``
          lines 2..N: one ``GoldCase`` per line
        """
        text = Path(path).read_text(encoding="utf-8")
        lines = [line for line in text.splitlines() if line.strip()]
        if not lines:
            raise ValueError(f"empty gold set file: {path}")
        header = json.loads(lines[0])
        if not header.get("cases_follow", False):
            raise ValueError(
                f"gold set header missing cases_follow=true: {path}"
            )
        cases: list[GoldCase] = []
        for raw in lines[1:]:
            cases.append(GoldCase.model_validate_json(raw))
        n_cases = header.get("n_cases", len(cases))
        if n_cases != len(cases):
            raise ValueError(
                f"header n_cases={n_cases} but {len(cases)} cases on disk in {path}"
            )
        return cls(
            version=header["version"],
            created_at=header["created_at"],
            n_cases=len(cases),
            cases=cases,
            label_provenance=header.get("label_provenance", ""),
        )

    def to_jsonl(self, path: Path) -> None:
        """Persist this gold set to ``path`` as JSONL (header + one case per line)."""
        header: dict[str, Any] = {
            "version": self.version,
            "created_at": self.created_at.isoformat(),
            "n_cases": self.n_cases,
            "label_provenance": self.label_provenance,
            "cases_follow": True,
        }
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(header, sort_keys=True)]
        for case in self.cases:
            lines.append(case.model_dump_json())
        out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


__all__ = ["GoldCase", "GoldSet"]
