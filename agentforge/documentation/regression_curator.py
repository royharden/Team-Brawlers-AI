"""Regression curator service on the Documentation Agent — master plan §8.4 + §13.

Every confirmed exploit becomes a deterministic regression case that the
`tb regress --case VR-####` command can replay. Hard invariant (master plan
§13 + testing-discipline contract): refuses to emit a case whose
`what_bug_this_catches` is empty.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agentforge.memory.schemas import MutatedAttack


class RegressionCuratorError(Exception):
    """Raised when an invariant of the regression curator is violated."""


class RegressionCurator:
    """Master plan §8.4 step 10: every confirmed exploit becomes a
    deterministic regression case. Refuses on empty what_bug_this_catches.
    """

    def __init__(self, regression_dir: Path) -> None:
        self.regression_dir = Path(regression_dir)
        self.regression_dir.mkdir(parents=True, exist_ok=True)

    def emit_case(
        self,
        *,
        vr_id: str,
        seed: dict[str, Any],
        attack: MutatedAttack,
        expected_safe_behavior: str,
        target_fingerprint: str,
        run_id: str,
        what_bug_this_catches: str,
    ) -> Path:
        """Write `<regression_dir>/<vr_id>.json`.

        REFUSES (raises `ValueError`) if `what_bug_this_catches` is empty or
        whitespace-only. Returns the path written.
        """
        if not what_bug_this_catches or not what_bug_this_catches.strip():
            raise ValueError(
                f"Refusing to emit regression case {vr_id}: "
                "what_bug_this_catches is empty (master plan §13)"
            )

        prompt = (
            attack.rendered_prompt if attack.rendered_prompt is not None else seed.get("prompt", "")
        )

        case: dict[str, Any] = {
            "id": seed.get("id", vr_id),
            "vr_id": vr_id,
            "category": seed.get("category", attack.category),
            "subcategory": seed.get("subcategory", ""),
            "prompt": prompt,
            "expected_safe_behavior": expected_safe_behavior,
            "what_bug_this_catches": what_bug_this_catches.strip(),
            "severity": seed.get("severity", "Medium"),
            "references": list(seed.get("references", [])),
            "regression_metadata": {
                "originating_run_id": run_id,
                "target_fingerprint_at_discovery": target_fingerprint,
                "replay_command": f"tb regress --case {vr_id}",
                "expected_outcome": "fail",
                "emitted_at": datetime.now(UTC).isoformat(),
            },
        }

        out_path = self.regression_dir / f"{vr_id}.json"
        # Atomic write: write to a temp file then rename.
        tmp_path = out_path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(case, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(tmp_path, out_path)
        return out_path


__all__ = ["RegressionCurator", "RegressionCuratorError"]
