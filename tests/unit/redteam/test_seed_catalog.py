"""SeedCatalog tests — master plan §8.2."""

from __future__ import annotations

import pytest

from agentforge.redteam.seed_catalog import SeedCatalog


@pytest.mark.unit
def test_all_returns_committed_seeds_across_every_category() -> None:
    """`SeedCatalog.all()` returns every committed seed across all 9 category YAMLs.

    History: the original test pinned len==15 from when _CATEGORIES only
    loaded 3 of the 9 committed YAMLs (prompt_injection, data_exfiltration,
    tool_misuse). C3-full / AgDR-0016 widened _CATEGORIES to all 9 so the
    orchestrator's planner can pick any of its 8 covered categories without
    triggering "no seeds for category" errors. The exact count is
    growing-and-shifting; we just assert "many" + per-category presence.
    """
    cat = SeedCatalog()
    seeds = cat.all()
    # 15 was the Phase-2/5 baseline (PI + data_exfil + tool_misuse only). Now
    # all 9 YAMLs load, so the total is ~3x. Floor of 30 leaves headroom for
    # future Phase-6+ additions without flaking.
    assert len(seeds) >= 30
    # Every category that the orchestrator's coverage matrix recognizes must
    # have at least one seed; otherwise the planner can route to a category
    # the Red Team can't serve.
    seeded_categories = {s.get("category") for s in seeds}
    for required in (
        "prompt_injection",
        "data_exfiltration",
        "tool_misuse",
        "state_corruption",
        "denial_of_service",
        "identity_role",
        "clinical_integrity",
        "observability_leakage",
    ):
        assert (
            required in seeded_categories
        ), f"category {required!r} has zero seeds; orchestrator planner will fail on it"


@pytest.mark.unit
def test_by_category_returns_only_in_category_seeds() -> None:
    """`SeedCatalog.by_category` returns only the requested category and `[]` for unknown."""
    cat = SeedCatalog()
    pi = cat.by_category("prompt_injection")
    assert pi
    assert all(s.get("category") == "prompt_injection" for s in pi)
    assert cat.by_category("does_not_exist") == []


@pytest.mark.unit
def test_by_id_returns_the_matching_seed_or_raises() -> None:
    """`SeedCatalog.by_id` returns the matching seed dict or raises `KeyError`."""
    cat = SeedCatalog()
    seed = cat.by_id("prompt_injection_persona_override")
    assert seed["category"] == "prompt_injection"
    assert seed["subcategory"] == "persona_override"
    with pytest.raises(KeyError):
        cat.by_id("not_a_real_seed_id")
