"""Pricing table unit tests — master plan §6, §15.

No live API calls; `resolve_models()` is exercised through an injected
fake client that mimics `anthropic.Anthropic.models.list()`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from agentforge.pricing import (
    ModelResolution,
    PricingStale,
    PricingTable,
    UnknownModel,
    resolve_models,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"


# --- PricingTable -------------------------------------------------------------


@pytest.mark.unit
def test_pricing_table_loads_yaml() -> None:
    """`PricingTable.from_yaml` parses fresh `config/pricing.yml` and registers known models (master plan §6)."""
    table = PricingTable.from_yaml(
        FIXTURES / "pricing_fresh.yml",
        today=date(2026, 5, 13),
        freshness_days=30,
    )
    assert table.retrieved_on == date(2026, 5, 1)
    assert "claude-sonnet-4-6" in table.known_models("anthropic")


@pytest.mark.unit
def test_pricing_stale_raises() -> None:
    """YAML older than 2x freshness window must raise `PricingStale` instead of silently using stale prices (master plan §15)."""
    with pytest.raises(PricingStale):
        PricingTable.from_yaml(
            FIXTURES / "pricing_old.yml",
            today=date(2026, 5, 13),
            freshness_days=30,
        )


@pytest.mark.unit
def test_pricing_stale_warning_logged(caplog: pytest.LogCaptureFixture) -> None:
    """Within 2x window but past freshness — should warn, not raise."""
    # 35-day-old snapshot, window=30 → warn but allow.
    table = PricingTable.from_yaml(
        FIXTURES / "pricing_fresh.yml",
        today=date(2026, 6, 5),  # 35 days after 2026-05-01
        freshness_days=30,
    )
    assert table is not None


@pytest.mark.unit
def test_cost_for_call_decimal() -> None:
    """Cost arithmetic returns `Decimal` with exact expected USD totals (master plan §6/§15 — no float drift)."""
    table = PricingTable.from_yaml(
        FIXTURES / "pricing_fresh.yml",
        today=date(2026, 5, 13),
        freshness_days=30,
    )
    cost = table.cost_for_call(
        provider="anthropic",
        model="claude-sonnet-4-6",
        input_tokens=1_000_000,
        output_tokens=500_000,
    )
    # 1M input @ $3 + 0.5M output @ $15 = 3.00 + 7.50 = 10.50
    assert isinstance(cost, Decimal)
    assert cost == Decimal("10.50")


@pytest.mark.unit
def test_cost_for_call_no_float_drift() -> None:
    """Confirm pricing arithmetic is `Decimal` end-to-end (no 0.30000000004)."""
    table = PricingTable.from_yaml(
        FIXTURES / "pricing_fresh.yml",
        today=date(2026, 5, 13),
        freshness_days=30,
    )
    cost = table.cost_for_call("anthropic", "claude-haiku-4-6", 100_000, 0)
    # 100K input @ $1/M = $0.10 — exact in Decimal, would drift in float.
    assert cost == Decimal("0.10")
    # Decimal arithmetic preserves exactness; float multiplication of
    # 100000 * (1/1_000_000) would yield 0.09999999999999999 on most systems.
    assert float(cost) == 0.1
    assert isinstance(cost, Decimal)


@pytest.mark.unit
def test_unknown_model_raises() -> None:
    """Unknown `(provider, model)` pair must raise `UnknownModel` (no silent $0 cost)."""
    table = PricingTable.from_yaml(
        FIXTURES / "pricing_fresh.yml",
        today=date(2026, 5, 13),
        freshness_days=30,
    )
    with pytest.raises(UnknownModel):
        table.cost_for_call("anthropic", "claude-opus-99", 1, 1)


# --- resolve_models() ---------------------------------------------------------


class _FakeListing:
    def __init__(self, ids: list[str]) -> None:
        self.data = [type("M", (), {"id": i})() for i in ids]


class _FakeModelsAPI:
    def __init__(self, ids: list[str]) -> None:
        self._ids = ids

    def list(self) -> _FakeListing:
        return _FakeListing(self._ids)


class _FakeAnthropicClient:
    def __init__(self, ids: list[str]) -> None:
        self.models = _FakeModelsAPI(ids)


@pytest.mark.unit
def test_resolve_models_anthropic_all_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """REDTEAM_PROVIDER=anthropic, all requested models present, no substitution.

    With AgDR-0013 the default REDTEAM_PROVIDER is `openrouter`; this test
    pins the legacy anthropic path explicitly.
    """
    monkeypatch.setenv("REDTEAM_PROVIDER", "anthropic")
    # Pin REDTEAM_MODEL to a valid Anthropic name so the resolver doesn't
    # substitute. Without this, a .env containing the AgDR-0013 default
    # (cognitivecomputations/dolphin-mistral-24b-venice-edition:free) bleeds
    # into MainConfig.anthropic.redteam_model and forces a substitution.
    monkeypatch.setenv("REDTEAM_MODEL", "claude-sonnet-4-6")
    from agentforge.config import get_settings

    get_settings.cache_clear()
    try:
        fake = _FakeAnthropicClient(["claude-sonnet-4-6", "claude-haiku-4-6", "claude-haiku-4-5"])
        result = resolve_models(anthropic_client=fake)
        assert isinstance(result, ModelResolution)
        assert result.resolved["orchestrator"] == "claude-sonnet-4-6"
        # Sub-plan Next05 §3: default fast model swapped to haiku-4-5
        # (the real shipped SKU; haiku-4-6 was a phantom name that 404'd).
        assert result.resolved["fast"] == "claude-haiku-4-5"
        assert result.substitutions == []
    finally:
        get_settings.cache_clear()


@pytest.mark.unit
def test_resolve_models_fast_resolves_to_haiku_45() -> None:
    """When haiku-4-5 is the configured fast model AND it's published, the
    resolver returns it directly with no substitution (sub-plan Next05 §3 —
    haiku-4-5 IS the default; the haiku-4-6→4-5 substitution scenario this
    test used to pin no longer applies because 4-6 is no longer the default).
    """
    fake = _FakeAnthropicClient(["claude-sonnet-4-6", "claude-haiku-4-5"])
    result = resolve_models(anthropic_client=fake)
    assert result.resolved["fast"] == "claude-haiku-4-5"
    # No substitution — the configured model is published.
    assert all("fast:" not in s for s in result.substitutions)


@pytest.mark.unit
def test_resolve_models_fireworks_substitution_logged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When REDTEAM_PROVIDER=fireworks but no Fireworks key/SDK, the resolver
    documents the AgDR-0001 substitution and returns Sonnet for the red team."""
    from agentforge import pricing as pricing_mod
    from agentforge.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("REDTEAM_PROVIDER", "fireworks")
    monkeypatch.setenv("FIREWORKS_API_KEY", "")

    fake = _FakeAnthropicClient(["claude-sonnet-4-6", "claude-haiku-4-6", "claude-haiku-4-5"])
    # No fireworks_models_list_fn → substitution path.
    result = pricing_mod.resolve_models(anthropic_client=fake)
    assert result.resolved["redteam"] == "claude-sonnet-4-6"
    assert any("AgDR-0001" in s for s in result.substitutions)

    # Cleanup: clear settings cache so next test re-reads env.
    get_settings.cache_clear()
