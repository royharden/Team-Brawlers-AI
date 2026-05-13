"""SeedCatalog tests — master plan §8.2."""

from __future__ import annotations

import pytest

from agentforge.redteam.seed_catalog import SeedCatalog


@pytest.mark.unit
def test_all_returns_twelve_committed_seeds() -> None:
    cat = SeedCatalog()
    seeds = cat.all()
    assert len(seeds) == 12  # 4 + 4 + 4 across the three categories


@pytest.mark.unit
def test_by_category_returns_only_in_category_seeds() -> None:
    cat = SeedCatalog()
    pi = cat.by_category("prompt_injection")
    assert pi
    assert all(s.get("category") == "prompt_injection" for s in pi)
    assert cat.by_category("does_not_exist") == []


@pytest.mark.unit
def test_by_id_returns_the_matching_seed_or_raises() -> None:
    cat = SeedCatalog()
    seed = cat.by_id("prompt_injection_persona_override")
    assert seed["category"] == "prompt_injection"
    assert seed["subcategory"] == "persona_override"
    with pytest.raises(KeyError):
        cat.by_id("not_a_real_seed_id")
