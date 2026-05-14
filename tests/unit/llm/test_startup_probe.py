"""Tests for the startup model self-test — Next06 §1 (AgDR-0027 follow-on).

These tests inject probe callables to avoid any real provider HTTP I/O.
The point of the production code is to surface phantom-SKU regressions
(like the AgDR-0027 `claude-haiku-4-6` 404) loudly; the point of these
tests is to pin the (provider, role, model) row shape so a future
refactor that drops a provider from the probe loop fails fast.
"""

from __future__ import annotations

import pytest

from agentforge.config import (
    AdapterConfig,
    AnthropicConfig,
    BudgetConfig,
    FireworksConfig,
    LangfuseConfig,
    MainConfig,
    OpenAIConfig,
    OpenRouterConfig,
)
from agentforge.llm.startup_probe import ProbeResult, probe_all_configured_models


def _make_cfg(
    *,
    anthropic_key: str = "test-anthropic-key",
    openrouter_key: str = "test-openrouter-key",
    openai_key: str = "test-openai-key",
    redteam_provider: str = "openrouter",
    openrouter_fallback: str | None = None,
) -> MainConfig:
    """Build a MainConfig with hermetic values via ``model_construct``.

    Pydantic-Settings reads `.env` on regular construction, which would
    leak the operator's real keys into assertions. ``model_construct``
    bypasses validation + env loading — the same pattern
    `tests/unit/target_adapter/test_sidecar_direct.py` uses.
    """
    default_fb = "cognitivecomputations/dolphin-mistral-24b-venice-edition:free"
    fb = openrouter_fallback if openrouter_fallback is not None else default_fb
    return MainConfig.model_construct(
        redteam_provider=redteam_provider,
        platform_db_url="sqlite:///:memory:",
        agent_message_signing_secret="test-secret",
        pricing_yml_freshness_days=30,
        anthropic=AnthropicConfig.model_construct(
            api_key=anthropic_key,
            api_key_redteam="",
            api_key_judge="",
            orchestrator_model="claude-sonnet-4-6",
            fast_model="claude-haiku-4-5",
            fast_fallback_model="claude-haiku-4-5",
            redteam_model="claude-sonnet-4-6",
        ),
        openrouter=OpenRouterConfig.model_construct(
            api_key=openrouter_key,
            base_url="https://openrouter.ai/api/v1",
            redteam_model="cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
            redteam_fallback_model=fb,
            http_referer="",
            x_title="AgentForge",
        ),
        fireworks=FireworksConfig.model_construct(),
        openai=OpenAIConfig.model_construct(
            api_key=openai_key,
            redteam_model="gpt-4o-mini",
        ),
        langfuse=LangfuseConfig.model_construct(),
        budget=BudgetConfig.model_construct(per_attack_timeout_s=5),
        adapter=AdapterConfig.model_construct(),
    )


def _ok_probe(*args, **kwargs) -> ProbeResult:
    role = kwargs.get("role", "unknown")
    provider = kwargs.get("provider", "anthropic")
    model = args[1] if len(args) >= 2 else kwargs.get("model", "?")
    return ProbeResult(
        provider=provider,
        role=role,
        model=model,
        status="ok",
        latency_ms=12,
    )


def _err_probe_for(model_substr: str):
    """Build a probe stub that fails for any call whose model contains
    `model_substr` and succeeds otherwise — pin the AgDR-0027 regression
    pattern (one specific phantom SKU 404s; the rest are fine)."""

    def _probe(*args, **kwargs) -> ProbeResult:
        role = kwargs.get("role", "unknown")
        provider = kwargs.get("provider", "anthropic")
        model = args[1] if len(args) >= 2 else kwargs.get("model", "?")
        if model_substr in model:
            return ProbeResult(
                provider=provider,
                role=role,
                model=model,
                status="error",
                error=f"404 not_found: model {model}",
                latency_ms=42,
            )
        return ProbeResult(
            provider=provider,
            role=role,
            model=model,
            status="ok",
            latency_ms=15,
        )

    return _probe


@pytest.mark.unit
def test_probe_returns_one_row_per_configured_model() -> None:
    """All providers configured + distinct primary/fallback → 5 rows:
    Haiku, Sonnet, OpenRouter primary, OpenRouter fallback, OpenAI."""
    cfg = _make_cfg(openrouter_fallback="meta-llama/llama-3.1-8b-instruct:free")
    results = probe_all_configured_models(
        cfg,
        anthropic_probe=_ok_probe,
        openai_compat_probe=_ok_probe,
    )
    assert len(results) == 5
    roles = {r.role for r in results}
    assert roles == {
        "internal_judge",
        "orchestrator_planner",
        "red_team_primary",
        "red_team_fallback",
        "red_team_openai_fallback",
    }
    assert all(r.status == "ok" for r in results)


@pytest.mark.unit
def test_probe_skips_duplicate_openrouter_fallback() -> None:
    """When OpenRouter primary == fallback (the `:free` Dolphin default),
    only the primary is probed — duplicate round-trip would waste tokens."""
    cfg = _make_cfg(openrouter_fallback=None)  # defaults primary==fallback
    results = probe_all_configured_models(
        cfg,
        anthropic_probe=_ok_probe,
        openai_compat_probe=_ok_probe,
    )
    roles = [r.role for r in results]
    assert "red_team_primary" in roles
    assert "red_team_fallback" not in roles


@pytest.mark.unit
def test_probe_surfaces_phantom_sku_as_error_row() -> None:
    """The whole point — phantom SKU 404 (the AgDR-0027 regression
    pattern) produces a `status=error` row. A real Anthropic 404 looks
    exactly like this; this test catches a regression that nukes the
    error-row path."""
    cfg = _make_cfg()
    results = probe_all_configured_models(
        cfg,
        anthropic_probe=_err_probe_for("haiku"),
        openai_compat_probe=_ok_probe,
    )
    haiku_row = next(r for r in results if "haiku" in r.model)
    assert haiku_row.status == "error"
    assert "404" in (haiku_row.error or "")
    # Sonnet still ok → error is local to Haiku
    sonnet_row = next(r for r in results if "sonnet" in r.model)
    assert sonnet_row.status == "ok"


@pytest.mark.unit
def test_probe_emits_missing_key_for_unconfigured_optional_provider() -> None:
    """Operator with no OpenAI key configured → the AgDR-0024 fallback
    row shows `missing_key`, NOT `error`. The UI can colour these
    differently so missing optional providers don't look like outages."""
    cfg = _make_cfg(openai_key="")
    results = probe_all_configured_models(
        cfg,
        anthropic_probe=_ok_probe,
        openai_compat_probe=_ok_probe,
    )
    openai_row = next(r for r in results if r.provider == "openai")
    assert openai_row.status == "missing_key"
    assert openai_row.error is None


@pytest.mark.unit
def test_probe_emits_missing_key_for_unconfigured_anthropic() -> None:
    """No Anthropic key → both Haiku + Sonnet rows are `missing_key`."""
    cfg = _make_cfg(anthropic_key="")
    results = probe_all_configured_models(
        cfg,
        anthropic_probe=_ok_probe,
        openai_compat_probe=_ok_probe,
    )
    anthropic_rows = [r for r in results if r.provider == "anthropic"]
    assert len(anthropic_rows) == 2
    assert all(r.status == "missing_key" for r in anthropic_rows)


@pytest.mark.unit
def test_probe_only_pings_redteam_provider_thats_active() -> None:
    """`redteam_provider=anthropic` → no OpenRouter rows.

    This pins AgDR-0013's provider-selection invariant — when the
    operator overrides the Red Team backend, we don't waste OpenRouter
    quota probing a backend we won't use.
    """
    cfg = _make_cfg(redteam_provider="anthropic")
    results = probe_all_configured_models(
        cfg,
        anthropic_probe=_ok_probe,
        openai_compat_probe=_ok_probe,
    )
    assert not any(r.provider == "openrouter" for r in results)
