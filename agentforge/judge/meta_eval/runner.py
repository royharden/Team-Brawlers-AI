"""Judge meta-eval runner — master plan §10 / §22 (DoD 16).

Replays a hand-labeled :class:`GoldSet` through the External Final Judge (and
optionally the Internal Progress Judge), aggregates per-case predictions into
:class:`JudgeMetrics`, and writes the metrics to
``evals/meta_eval/judge_<layer>_<version>_metrics.json``.

The judge is invoked through its public ``score(...)`` method using
``MutatedAttack`` + ``AdapterResponse`` envelopes synthesized from the gold-case
text fields. No live network calls are made — gold cases focus on deterministic
rubrics, so the External Final Judge's no-client path produces a stable verdict.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any, Literal

from agentforge.judge.external_final import ExternalFinalJudge
from agentforge.judge.internal_progress import InternalProgressJudge
from agentforge.judge.meta_eval.gold_set_schema import GoldCase, GoldSet
from agentforge.judge.meta_eval.metrics import (
    DEFAULT_FLOOR,
    JudgeMetrics,
    compute_judge_metrics,
)
from agentforge.judge.rubrics import RubricRegistry
from agentforge.memory.schemas import AdapterResponse, MutatedAttack


DEFAULT_OUTPUT_DIR: Path = Path("evals") / "meta_eval"
DEFAULT_GOLD_SET_PATH: Path = Path("evals") / "meta_eval" / "gold_set" / "v1.jsonl"


def _build_envelope(case: GoldCase) -> tuple[MutatedAttack, AdapterResponse]:
    """Synthesize the ``(MutatedAttack, AdapterResponse)`` pair the judge expects.

    The attack carries a default ``packet`` (synthetic patient ``Alice Test``)
    plus a default ``task_token`` so the data-exfiltration and tool-misuse
    rubrics have the envelope shape they require. Gold cases that exercise a
    different patient context can override by supplying overrides in
    ``case.notes`` (not used in v1).
    """
    seed_used: dict[str, Any] = {
        "task_token": {
            "patient_id": "AliceTest",
            "user_id": "clinician_001",
        },
        "packet": {
            "patient_id": "AliceTest",
            "patient_name": "Alice Test",
            "dob": "1985-04-12",
            "dob_window": ["1985-01-01", "1986-12-31"],
            "authorized_patients": ["Alice Test", "AliceTest"],
        },
        "tool_allowlist": [
            "get_patient_identity",
            "get_active_problems",
            "get_active_medications",
            "get_allergy_list",
            "get_recent_labs",
            "get_immunization_history",
            "attach_and_extract",
        ],
    }
    attack = MutatedAttack(
        attack_id=str(uuid.uuid4()),
        seed_id=f"gold:{case.case_id}",
        category=case.category,
        strategy="single_turn",
        rendered_prompt=case.attack_prompt,
        mutator_chain=[],
        seed_used=seed_used,
    )
    response = AdapterResponse(
        attack_id=uuid.uuid4(),
        status_code=200,
        body_text=case.target_response,
        body_json=case.target_body_json,
    )
    return attack, response


def _predicted_label(failed_rubrics: list[str]) -> Literal["passed", "failed"]:
    """Predicted aggregate label.

    A rubric outcome of ``failed`` flips the case to ``failed``; abstains and
    ``not_applicable`` do NOT flip the label.
    """
    return "failed" if failed_rubrics else "passed"


def _load_floor_from_disk(layer: str) -> dict[str, float]:
    """Best-effort load of ``evals/floor.json::judge_floor.<layer>``."""
    floor_path = Path("evals") / "floor.json"
    if not floor_path.is_file():
        return dict(DEFAULT_FLOOR)
    try:
        data = json.loads(floor_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_FLOOR)
    judge_floor = data.get("judge_floor", {})
    layer_floor = judge_floor.get(layer)
    if isinstance(layer_floor, dict):
        return {
            "precision": float(layer_floor.get("precision", DEFAULT_FLOOR["precision"])),
            "recall": float(layer_floor.get("recall", DEFAULT_FLOOR["recall"])),
            "f1": float(layer_floor.get("f1", DEFAULT_FLOOR["f1"])),
        }
    return dict(DEFAULT_FLOOR)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write ``payload`` as JSON to ``path`` atomically (temp-file + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class MetaEvalRunner:
    """Runs the External (and optionally Internal) judge against a gold set."""

    def __init__(
        self,
        external_judge: ExternalFinalJudge,
        internal_judge: InternalProgressJudge | None = None,
        output_dir: Path | None = None,
    ) -> None:
        self._external = external_judge
        self._internal = internal_judge
        self._output_dir = Path(output_dir) if output_dir is not None else DEFAULT_OUTPUT_DIR

    def run(
        self,
        gold_set: GoldSet,
        *,
        layer: Literal["external_final", "internal_progress"] = "external_final",
        floor: dict[str, float] | None = None,
    ) -> JudgeMetrics:
        """Score every gold case, aggregate, persist metrics, return them."""
        if layer == "internal_progress" and self._internal is None:
            raise ValueError(
                "layer='internal_progress' requested but no InternalProgressJudge "
                "was provided to MetaEvalRunner"
            )

        predictions: list[tuple[str, str]] = []
        gold_pairs: list[tuple[str, str]] = []
        for case in gold_set.cases:
            attack, response = _build_envelope(case)
            if layer == "external_final":
                verdict = self._external.score(
                    attack, response, case.expected_safe_behavior
                )
                failed_rubrics = list(verdict.failed_rubrics)
            else:
                assert self._internal is not None
                verdict = self._internal.score(  # type: ignore[attr-defined]
                    attack, response, case.expected_safe_behavior
                )
                failed_rubrics = [
                    rid
                    for rid, outcome in verdict.outcomes.items()
                    if not outcome.passed and not outcome.abstained
                ]
            predictions.append((case.case_id, _predicted_label(failed_rubrics)))
            gold_pairs.append((case.case_id, case.expected_label))

        resolved_floor = floor if floor is not None else _load_floor_from_disk(layer)
        metrics = compute_judge_metrics(
            layer=layer,
            predictions=predictions,
            gold=gold_pairs,
            floor=resolved_floor,
        )

        out_path = (
            self._output_dir
            / f"judge_{layer}_{gold_set.version}_metrics.json"
        )
        payload: dict[str, Any] = {
            "layer": metrics.layer,
            "gold_set_version": gold_set.version,
            "n_cases": gold_set.n_cases,
            "metrics": metrics.model_dump(),
            "floor": resolved_floor,
            "predictions": [
                {"case_id": cid, "predicted_label": label}
                for cid, label in predictions
            ],
        }
        _atomic_write_json(out_path, payload)
        return metrics


def run_meta_eval(
    gold_set_path: Path | None = None,
    *,
    layer: str = "external_final",
    output_dir: Path | None = None,
    external_judge: ExternalFinalJudge | None = None,
) -> JudgeMetrics:
    """Module-level entry point the CLI (``tb meta-eval``) calls.

    If ``external_judge`` is None, instantiates one with the live
    :class:`RubricRegistry` and no LLM client — non-deterministic rubrics
    abstain, which is fine for v1 because all gold cases focus on
    deterministic rubrics.
    """
    if layer not in ("external_final", "internal_progress"):
        raise ValueError(
            f"layer must be 'external_final' or 'internal_progress'; got {layer!r}"
        )
    if external_judge is None:
        external_judge = ExternalFinalJudge(RubricRegistry())
    path = Path(gold_set_path) if gold_set_path is not None else DEFAULT_GOLD_SET_PATH
    gold_set = GoldSet.from_jsonl(path)
    runner = MetaEvalRunner(external_judge=external_judge, output_dir=output_dir)
    return runner.run(gold_set, layer=layer)  # type: ignore[arg-type]


__all__ = ["MetaEvalRunner", "run_meta_eval", "DEFAULT_OUTPUT_DIR"]
