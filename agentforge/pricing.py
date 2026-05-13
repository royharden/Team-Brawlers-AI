"""Pricing table loader + model resolution — master plan §6, §15.

Real implementation:
    - `PricingTable.from_yaml(path)` loads + validates freshness.
    - `PricingTable.cost_for_call(...)` returns `Decimal` USD cost.
    - `resolve_models()` queries Anthropic (and optionally Fireworks) `models.list`
      and records substitutions per AgDR-0001.

NO live API calls in tests — `resolve_models()` is HTTP-mocked via `respx`.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from loguru import logger
from pydantic import BaseModel, Field

from agentforge.config import get_settings


class PricingError(Exception):
    """Base class for pricing-table errors."""


class PricingStale(PricingError):
    """Raised when `retrieved_on` is older than 2x the freshness window."""


class UnknownModel(PricingError):
    """Raised when `cost_for_call` is asked for a model not in the table."""


class ModelResolution(BaseModel):
    """Result of the startup `models.list()` resolution dance.

    Persisted to `runs.model_resolution_json`. The platform stores what was
    requested vs what actually got resolved, plus any substitutions logged
    against an AgDR.
    """

    requested: dict[str, str] = Field(default_factory=dict)
    resolved: dict[str, str] = Field(default_factory=dict)
    substitutions: list[str] = Field(default_factory=list)
    resolved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# --- PricingTable -------------------------------------------------------------


class PricingTable:
    """Loads `config/pricing.yml`; resolves USD cost per (provider, model, tokens).

    Uses `Decimal` arithmetic throughout — no float drift in cost ledgers.
    """

    def __init__(
        self,
        table: dict[str, Any],
        retrieved_on: date,
    ) -> None:
        self._table = table
        self.retrieved_on = retrieved_on

    # ---- construction --------------------------------------------------------

    @classmethod
    def from_yaml(
        cls,
        path: Path,
        *,
        today: date | None = None,
        freshness_days: int | None = None,
    ) -> PricingTable:
        """Load `config/pricing.yml`, validate freshness.

        - Logs a warning if older than `freshness_days` (default from settings).
        - Raises `PricingStale` if older than 2x that window.
        """
        if not path.exists():
            raise PricingError(f"pricing yaml not found: {path}")

        raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        retrieved_on_raw = raw.get("retrieved_on")
        if retrieved_on_raw is None:
            raise PricingError("pricing yaml missing `retrieved_on`")

        retrieved_on = _coerce_date(retrieved_on_raw)
        today = today or date.today()
        freshness_days = (
            freshness_days
            if freshness_days is not None
            else get_settings().pricing_yml_freshness_days
        )
        age_days = (today - retrieved_on).days

        if age_days > 2 * freshness_days:
            raise PricingStale(
                f"pricing.yml retrieved_on {retrieved_on} is {age_days} days old "
                f"(> 2x freshness window of {freshness_days} days)"
            )
        if age_days > freshness_days:
            logger.warning(
                "pricing.yml is stale: retrieved_on={} is {} days old (window={}d)",
                retrieved_on,
                age_days,
                freshness_days,
            )

        # Drop the metadata key — only provider sub-tables remain.
        table = {k: v for k, v in raw.items() if k != "retrieved_on"}
        return cls(table=table, retrieved_on=retrieved_on)

    # ---- cost ----------------------------------------------------------------

    def cost_for_call(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> Decimal:
        """Return USD cost for one LLM call as a `Decimal`."""
        provider_table = self._table.get(provider)
        if not provider_table or model not in provider_table:
            raise UnknownModel(f"unknown model in pricing.yml: {provider}/{model}")

        prices = provider_table[model]
        per_m_in = Decimal(str(prices["input_per_million"]))
        per_m_out = Decimal(str(prices["output_per_million"]))
        million = Decimal("1000000")

        in_cost = (Decimal(input_tokens) * per_m_in) / million
        out_cost = (Decimal(output_tokens) * per_m_out) / million
        return in_cost + out_cost

    # ---- introspection -------------------------------------------------------

    def known_models(self, provider: str) -> list[str]:
        """List models registered under `provider`. Empty list if unknown provider."""
        provider_table = self._table.get(provider) or {}
        return list(provider_table.keys())


def _coerce_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise PricingError(f"unsupported retrieved_on type: {type(value)!r}")


# --- Model resolution ---------------------------------------------------------


def resolve_models(
    *,
    anthropic_client: Any | None = None,
    fireworks_models_list_fn: Any | None = None,
) -> ModelResolution:
    """Confirm that the requested orchestrator/fast/red-team models exist.

    For Anthropic: calls `client.models.list()` and looks for the requested model
    IDs. If `fast_model` is missing, falls back to `fast_fallback_model` and logs
    a substitution.

    For `REDTEAM_PROVIDER=fireworks`: attempts a Fireworks listing (if SDK + key
    available); on any failure, falls back to Anthropic Sonnet and logs the
    AgDR-0001 substitution.

    Parameters
    ----------
    anthropic_client:
        Optional injected client (used by tests). When None, builds one from
        `anthropic.Anthropic(api_key=...)`.
    fireworks_models_list_fn:
        Optional injected callable returning an iterable of fireworks model IDs.
        When None and the SDK is unavailable, the fireworks branch is treated
        as a failure (substitution path).
    """
    cfg = get_settings()

    requested: dict[str, str] = {
        "orchestrator": cfg.anthropic.orchestrator_model,
        "fast": cfg.anthropic.fast_model,
        "fast_fallback": cfg.anthropic.fast_fallback_model,
    }
    if cfg.redteam_provider == "anthropic":
        requested["redteam"] = cfg.anthropic.redteam_model
    else:
        requested["redteam"] = cfg.fireworks.redteam_model

    resolved: dict[str, str] = {}
    substitutions: list[str] = []

    # --- Anthropic ------------------------------------------------------------
    anthropic_ids: set[str] = set()
    try:
        client = anthropic_client or _build_anthropic_client(cfg)
        listing = client.models.list()
        anthropic_ids = {_extract_model_id(m) for m in _iter_listing(listing)}
    except Exception as exc:  # noqa: BLE001 — log + continue with empty set
        logger.warning("anthropic models.list() failed: {}", exc)

    resolved["orchestrator"] = _pick(
        requested["orchestrator"],
        candidates=[requested["orchestrator"]],
        available=anthropic_ids,
        substitutions=substitutions,
        role="orchestrator",
    )
    resolved["fast"] = _pick(
        requested["fast"],
        candidates=[requested["fast"], requested["fast_fallback"]],
        available=anthropic_ids,
        substitutions=substitutions,
        role="fast",
    )
    resolved["fast_fallback"] = requested["fast_fallback"]

    # --- Red Team -------------------------------------------------------------
    if cfg.redteam_provider == "anthropic":
        resolved["redteam"] = _pick(
            requested["redteam"],
            candidates=[requested["redteam"], cfg.anthropic.orchestrator_model],
            available=anthropic_ids,
            substitutions=substitutions,
            role="redteam",
        )
    else:
        resolved["redteam"] = _resolve_fireworks_redteam(
            cfg=cfg,
            fireworks_models_list_fn=fireworks_models_list_fn,
            anthropic_ids=anthropic_ids,
            substitutions=substitutions,
        )

    return ModelResolution(
        requested=requested,
        resolved=resolved,
        substitutions=substitutions,
    )


def _build_anthropic_client(cfg: Any) -> Any:
    """Construct a real Anthropic client. Lazy import so tests can inject."""
    from anthropic import Anthropic  # type: ignore[import-not-found]

    api_key = cfg.anthropic.api_key or ""
    return Anthropic(api_key=api_key)


def _iter_listing(listing: Any) -> Any:
    """Anthropic SDK returns a SyncPage; iterate `.data` if present, else self."""
    data = getattr(listing, "data", None)
    return data if data is not None else listing


def _extract_model_id(obj: Any) -> str:
    if isinstance(obj, str):
        return obj
    for attr in ("id", "name"):
        v = getattr(obj, attr, None)
        if isinstance(v, str):
            return v
    if isinstance(obj, dict):
        for key in ("id", "name"):
            v = obj.get(key)
            if isinstance(v, str):
                return v
    return ""


def _pick(
    requested: str,
    *,
    candidates: list[str],
    available: set[str],
    substitutions: list[str],
    role: str,
) -> str:
    """Pick the first candidate that is in `available`. If none, log subs and
    fall back to the first candidate verbatim (the runtime will surface the
    real error when the call is attempted).
    """
    for cand in candidates:
        if cand in available:
            if cand != requested:
                substitutions.append(
                    f"{role}: requested {requested!r}, substituted {cand!r} "
                    "(fast-fallback configured)"
                )
            return cand
    if available:
        substitutions.append(
            f"{role}: requested {requested!r} not found in provider listing; "
            "keeping requested value and deferring failure to call-time"
        )
    return requested


def _resolve_fireworks_redteam(
    *,
    cfg: Any,
    fireworks_models_list_fn: Any | None,
    anthropic_ids: set[str],
    substitutions: list[str],
) -> str:
    """Try to confirm the Fireworks red-team model. On any failure, document
    the AgDR-0001 substitution and return Anthropic Sonnet.
    """
    requested = cfg.fireworks.redteam_model
    try:
        if fireworks_models_list_fn is None:
            # Try SDK; if not installed, treat as failure.
            try:
                import fireworks  # type: ignore[import-not-found]  # noqa: F401
            except ImportError as exc:
                raise RuntimeError("fireworks SDK not installed") from exc
            if not cfg.fireworks.api_key:
                raise RuntimeError("FIREWORKS_API_KEY not set")
            # Without a stable SDK contract we don't speculate here — the
            # injected callable is the testable path.
            raise RuntimeError("no fireworks_models_list_fn provided")

        ids = {str(m) for m in fireworks_models_list_fn()}
        if requested in ids:
            return requested
        if cfg.fireworks.redteam_fallback_model in ids:
            substitutions.append(
                f"redteam: requested {requested!r}, substituted fireworks "
                f"fallback {cfg.fireworks.redteam_fallback_model!r}"
            )
            return cfg.fireworks.redteam_fallback_model
        raise RuntimeError("requested fireworks model not in listing")
    except Exception as exc:  # noqa: BLE001 — substitution path is the goal.
        sonnet = cfg.anthropic.orchestrator_model
        substitutions.append(
            f"redteam: fireworks unreachable ({exc}); substituting Anthropic "
            f"{sonnet!r} per AgDR-0001"
        )
        logger.warning(
            "Fireworks red-team substitution invoked (AgDR-0001): {}", exc
        )
        return sonnet
