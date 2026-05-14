"""Startup model self-test — pings every configured LLM at boot.

Motivation (lesson from AgDR-0027): the platform shipped for sprints with
``ANTHROPIC_FAST_MODEL=claude-haiku-4-6``, a phantom SKU that returned 404
on every Internal-Judge call. Because each Haiku call's failure path
degraded silently to ``abstain``, nothing in the dashboard, the test
suite, or the cost ledger surfaced the problem — only a manual live
``tb attack`` log read did, after the model had been broken for days.

This module gives the platform a cheap, predictable way to detect that
class of regression early: a minimal probe call to each model the factory
would use (Anthropic Sonnet + Haiku, OpenRouter Red Team primary +
fallback, OpenAI direct Red Team fallback). The probes are pure functions
of (api_key, model, base_url); ``probe_all_configured_models`` walks the
``MainConfig`` and returns one row per (provider, role, model) configured
for the running instance. Missing API keys produce a ``missing_key``
status row rather than a probe — the operator decides whether that is
expected (e.g. AgDR-0024 OpenAI fallback is optional).

The probe path is intentionally NOT wired into FastAPI's startup hook by
default — burning provider tokens on every uvicorn reload is the wrong
trade-off for dev iteration. Instead, the ``GET /v1/startup-probe``
endpoint runs it on demand, and operators can curl it after deploys or
add it to the Cost / Dashboard UI for a permanent "is every model
reachable?" surface.

Provider-isolation note: this module imports both ``anthropic`` and
``openai`` SDKs. It lives under ``agentforge.llm.*`` (NOT under
``agentforge.judge.*`` or ``agentforge.redteam.*``), so neither the
judge-independence lint nor the Red Team provider-isolation lint applies.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from loguru import logger

from agentforge.config import MainConfig, get_settings

# Tiny probe payloads — minimize provider spend while still exercising the
# full request path (auth + model resolution + response parse).
_PROBE_PROMPT: str = "ok"
_PROBE_MAX_TOKENS: int = 8


@dataclass(frozen=True)
class ProbeResult:
    """One model's reachability check.

    ``status`` is one of:
    - ``ok``           — provider returned a successful response.
    - ``error``        — provider returned a non-2xx or the SDK raised.
    - ``missing_key``  — no API key configured; probe skipped.
    - ``skipped``      — provider explicitly disabled (e.g. fireworks).
    """

    provider: str
    role: str
    model: str
    status: str
    error: str | None = None
    latency_ms: int | None = None


# --------------------------------------------------------------------------- probes


def _probe_anthropic(
    api_key: str,
    model: str,
    *,
    role: str,
    client_factory: Callable[[str], Any] | None = None,
) -> ProbeResult:
    """Send a minimal ``messages.create`` request to Anthropic.

    ``client_factory`` is injectable for tests — production wires
    ``anthropic.Anthropic`` lazily so this module imports cleanly even
    when the operator has no Anthropic key set.
    """
    started = time.monotonic()
    try:
        if client_factory is None:
            import anthropic

            client = anthropic.Anthropic(api_key=api_key)
        else:
            client = client_factory(api_key)
        client.messages.create(
            model=model,
            max_tokens=_PROBE_MAX_TOKENS,
            messages=[{"role": "user", "content": _PROBE_PROMPT}],
        )
    except Exception as exc:  # broad on purpose — surfaces SDK + HTTP errors
        latency_ms = int((time.monotonic() - started) * 1000)
        return ProbeResult(
            provider="anthropic",
            role=role,
            model=model,
            status="error",
            error=str(exc),
            latency_ms=latency_ms,
        )
    latency_ms = int((time.monotonic() - started) * 1000)
    return ProbeResult(
        provider="anthropic",
        role=role,
        model=model,
        status="ok",
        latency_ms=latency_ms,
    )


def _probe_openai_compat(
    api_key: str,
    model: str,
    *,
    provider: str,
    role: str,
    base_url: str | None = None,
    client_factory: Callable[..., Any] | None = None,
) -> ProbeResult:
    """Send a minimal ``chat.completions.create`` request via the OpenAI
    SDK. Works for both OpenRouter (``base_url=openrouter.ai/api/v1``) and
    direct OpenAI (``base_url=None``) — exactly the pattern the two Red
    Team clients use.
    """
    started = time.monotonic()
    try:
        if client_factory is None:
            from openai import OpenAI

            kwargs: dict[str, Any] = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            client = OpenAI(**kwargs)
        else:
            client = client_factory(api_key=api_key, base_url=base_url)
        client.chat.completions.create(
            model=model,
            max_tokens=_PROBE_MAX_TOKENS,
            messages=[{"role": "user", "content": _PROBE_PROMPT}],
        )
    except Exception as exc:
        latency_ms = int((time.monotonic() - started) * 1000)
        return ProbeResult(
            provider=provider,
            role=role,
            model=model,
            status="error",
            error=str(exc),
            latency_ms=latency_ms,
        )
    latency_ms = int((time.monotonic() - started) * 1000)
    return ProbeResult(
        provider=provider,
        role=role,
        model=model,
        status="ok",
        latency_ms=latency_ms,
    )


# --------------------------------------------------------------------------- aggregate


def probe_all_configured_models(
    cfg: MainConfig | None = None,
    *,
    anthropic_probe: Callable[..., ProbeResult] | None = None,
    openai_compat_probe: Callable[..., ProbeResult] | None = None,
) -> list[ProbeResult]:
    """Probe every model the orchestrator factory would wire.

    Returns one row per (provider, role, model) configured for the
    running instance. Missing API keys produce ``missing_key`` rows
    rather than ``error`` rows — operators distinguish "this provider
    is optional and we didn't configure it" from "this provider failed."

    Tests inject the two ``*_probe`` callables to avoid real network I/O.
    """
    cfg = cfg or get_settings()
    a_probe = anthropic_probe or _probe_anthropic
    o_probe = openai_compat_probe or _probe_openai_compat
    results: list[ProbeResult] = []

    # ---- Anthropic -------------------------------------------------------
    if cfg.anthropic.api_key:
        results.append(
            a_probe(
                cfg.anthropic.api_key,
                cfg.anthropic.fast_model,
                role="internal_judge",
            )
        )
        results.append(
            a_probe(
                cfg.anthropic.api_key,
                cfg.anthropic.orchestrator_model,
                role="orchestrator_planner",
            )
        )
    else:
        results.append(
            ProbeResult(
                provider="anthropic",
                role="internal_judge",
                model=cfg.anthropic.fast_model,
                status="missing_key",
            )
        )
        results.append(
            ProbeResult(
                provider="anthropic",
                role="orchestrator_planner",
                model=cfg.anthropic.orchestrator_model,
                status="missing_key",
            )
        )

    # ---- OpenRouter (Red Team primary) ----------------------------------
    if cfg.redteam_provider == "openrouter":
        if cfg.openrouter.is_configured:
            results.append(
                o_probe(
                    cfg.openrouter.api_key,
                    cfg.openrouter.redteam_model,
                    provider="openrouter",
                    role="red_team_primary",
                    base_url=cfg.openrouter.base_url,
                )
            )
            # The fallback model is the OpenRouter-internal try-second-model
            # knob. We only probe it when it's different from the primary —
            # for the `:free` Dolphin default, primary == fallback, and an
            # extra round-trip is wasted tokens.
            if (
                cfg.openrouter.redteam_fallback_model
                and cfg.openrouter.redteam_fallback_model != cfg.openrouter.redteam_model
            ):
                results.append(
                    o_probe(
                        cfg.openrouter.api_key,
                        cfg.openrouter.redteam_fallback_model,
                        provider="openrouter",
                        role="red_team_fallback",
                        base_url=cfg.openrouter.base_url,
                    )
                )
        else:
            results.append(
                ProbeResult(
                    provider="openrouter",
                    role="red_team_primary",
                    model=cfg.openrouter.redteam_model,
                    status="missing_key",
                )
            )

    # ---- OpenAI direct (Red Team second-tier fallback, AgDR-0024) -------
    if cfg.openai.is_configured:
        results.append(
            o_probe(
                cfg.openai.api_key,
                cfg.openai.redteam_model,
                provider="openai",
                role="red_team_openai_fallback",
                base_url=None,
            )
        )
    else:
        # OpenAI is an optional fallback per AgDR-0024 — surface as
        # `missing_key` but don't flag it as an error in any UI.
        results.append(
            ProbeResult(
                provider="openai",
                role="red_team_openai_fallback",
                model=cfg.openai.redteam_model,
                status="missing_key",
            )
        )

    # Log a one-line summary at INFO level so anyone watching the API logs
    # sees the result without grepping. AgDR-0027 would have surfaced
    # immediately had this been wired.
    n_ok = sum(1 for r in results if r.status == "ok")
    n_err = sum(1 for r in results if r.status == "error")
    n_missing = sum(1 for r in results if r.status == "missing_key")
    logger.info(
        "startup_probe: ok={} error={} missing_key={} total={}",
        n_ok,
        n_err,
        n_missing,
        len(results),
    )
    for r in results:
        if r.status == "error":
            logger.warning(
                "startup_probe FAILED: provider={} role={} model={} error={}",
                r.provider,
                r.role,
                r.model,
                r.error,
            )

    return results


__all__ = [
    "ProbeResult",
    "probe_all_configured_models",
]
