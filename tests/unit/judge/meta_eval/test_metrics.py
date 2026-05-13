"""compute_judge_metrics tests — master plan §22 DoD 16."""

from __future__ import annotations

import pytest

from agentforge.judge.meta_eval.metrics import (
    DEFAULT_FLOOR,
    compute_judge_metrics,
)


@pytest.mark.unit
def test_perfect_judge_metrics() -> None:
    """Predictions == gold should yield 1.0 precision/recall/F1 and alpha=1.0."""
    predictions = [
        ("c1", "failed"),
        ("c2", "passed"),
        ("c3", "failed"),
        ("c4", "passed"),
    ]
    gold = list(predictions)
    metrics = compute_judge_metrics(
        layer="external_final",
        predictions=predictions,
        gold=gold,
    )
    assert metrics.precision == 1.0
    assert metrics.recall == 1.0
    assert metrics.f1 == 1.0
    assert metrics.krippendorff_alpha == 1.0
    assert metrics.n == 4
    assert metrics.n_correct == 4
    assert metrics.floor_met == {"precision": True, "recall": True, "f1": True}


@pytest.mark.unit
def test_random_judge_alpha_near_zero() -> None:
    """When predictions are completely uncorrelated with gold (50/50 mix and
    independent), Krippendorff's alpha should sit near zero — at most a small
    magnitude. With balanced 50/50 distributions a 50% mismatch rate yields
    alpha = 1 - (0.5/0.5) = 0.0 exactly."""
    gold = [
        ("c1", "failed"),
        ("c2", "passed"),
        ("c3", "failed"),
        ("c4", "passed"),
        ("c5", "failed"),
        ("c6", "passed"),
        ("c7", "failed"),
        ("c8", "passed"),
    ]
    # Independent predictions: flip every other case.
    predictions = [
        ("c1", "passed"),
        ("c2", "failed"),
        ("c3", "failed"),
        ("c4", "passed"),
        ("c5", "passed"),
        ("c6", "failed"),
        ("c7", "failed"),
        ("c8", "passed"),
    ]
    metrics = compute_judge_metrics(
        layer="external_final",
        predictions=predictions,
        gold=gold,
    )
    assert abs(metrics.krippendorff_alpha) <= 0.05


@pytest.mark.unit
def test_misaligned_case_ids_raises() -> None:
    """ValueError when prediction/gold case_ids do not match in order."""
    with pytest.raises(ValueError):
        compute_judge_metrics(
            layer="external_final",
            predictions=[("a", "failed"), ("b", "passed")],
            gold=[("a", "failed"), ("c", "passed")],
        )


@pytest.mark.unit
def test_all_same_label_alpha_perfect_on_match() -> None:
    """When all gold + pred labels are the same, alpha == 1.0 (no signal but
    no disagreement either)."""
    gold = [("c1", "passed"), ("c2", "passed"), ("c3", "passed")]
    predictions = list(gold)
    metrics = compute_judge_metrics(
        layer="external_final",
        predictions=predictions,
        gold=gold,
    )
    assert metrics.krippendorff_alpha == 1.0
    # Precision / recall are 0 because there are no positives.
    assert metrics.precision == 0.0
    assert metrics.recall == 0.0


@pytest.mark.unit
def test_floor_met_dict_populated() -> None:
    """floor_met carries one boolean per metric in the floor dict."""
    gold = [
        ("c1", "failed"),
        ("c2", "passed"),
        ("c3", "failed"),
        ("c4", "passed"),
    ]
    # All predictions say "failed" → recall=1.0, precision=0.5, f1=0.667
    predictions = [
        ("c1", "failed"),
        ("c2", "failed"),
        ("c3", "failed"),
        ("c4", "failed"),
    ]
    metrics = compute_judge_metrics(
        layer="external_final",
        predictions=predictions,
        gold=gold,
        floor=DEFAULT_FLOOR,
    )
    assert set(metrics.floor_met.keys()) == {"precision", "recall", "f1"}
    # precision = 0.5 < 0.85 → False; recall = 1.0 >= 0.80 → True; f1 ≈ 0.667 < 0.82 → False
    assert metrics.floor_met["precision"] is False
    assert metrics.floor_met["recall"] is True
    assert metrics.floor_met["f1"] is False
