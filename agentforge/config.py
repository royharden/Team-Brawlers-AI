"""Pydantic Settings — master plan §6 (canonical env vars mirror .env.example)."""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AnthropicConfig(BaseSettings):
    """Anthropic API config — primary backend for Judge/Orchestrator/Documentation.

    Note: as of AgDR-0013 the Red Team backend is OpenRouter Dolphin-Mistral
    24B Venice, NOT Anthropic. The `redteam_model` field below only matters
    when `REDTEAM_PROVIDER=anthropic` (the emergency-fallback path from
    superseded AgDR-0001).
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    api_key_redteam: str = Field(default="", alias="ANTHROPIC_API_KEY_REDTEAM")
    api_key_judge: str = Field(default="", alias="ANTHROPIC_API_KEY_JUDGE")
    orchestrator_model: str = Field(
        default="claude-sonnet-4-6", alias="ANTHROPIC_ORCHESTRATOR_MODEL"
    )
    fast_model: str = Field(default="claude-haiku-4-6", alias="ANTHROPIC_FAST_MODEL")
    fast_fallback_model: str = Field(
        default="claude-haiku-4-5", alias="ANTHROPIC_FAST_FALLBACK_MODEL"
    )
    redteam_model: str = Field(default="claude-sonnet-4-6", alias="REDTEAM_MODEL")


class OpenRouterConfig(BaseSettings):
    """OpenRouter config — primary Red Team backend per AgDR-0013.

    Uses the OpenAI-compatible REST API at https://openrouter.ai/api/v1.
    The `openai` Python SDK is the client.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    api_key: str = Field(default="", alias="OPENROUTER_API_KEY")
    base_url: str = Field(default="https://openrouter.ai/api/v1", alias="OPENROUTER_BASE_URL")
    redteam_model: str = Field(
        default="cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
        alias="OPENROUTER_REDTEAM_MODEL",
    )
    redteam_fallback_model: str = Field(
        default="cognitivecomputations/dolphin-mistral-24b-venice-edition",
        alias="OPENROUTER_REDTEAM_FALLBACK_MODEL",
    )
    http_referer: str = Field(default="", alias="OPENROUTER_HTTP_REFERER")
    x_title: str = Field(default="AgentForge", alias="OPENROUTER_X_TITLE")

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)


class FireworksConfig(BaseSettings):
    """Fireworks config — historical placeholder per AgDR-0013.

    Fireworks does NOT serve Dolphin-2.9.2-Qwen2-72B in their serverless
    catalog, so this provider is non-functional. Kept here so a future
    Fireworks reactivation is a one-line swap.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    api_key: str = Field(default="", alias="FIREWORKS_API_KEY")
    redteam_model: str = Field(
        default="accounts/fireworks/models/dolphin-2-9-2-qwen2-72b",
        alias="FIREWORKS_REDTEAM_MODEL",
    )
    redteam_fallback_model: str = Field(
        default="accounts/fireworks/models/nous-hermes-3-llama-3-1-70b",
        alias="FIREWORKS_REDTEAM_FALLBACK_MODEL",
    )


class LangfuseConfig(BaseSettings):
    """Langfuse observability config — master plan §12."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    public_key: str = Field(default="", alias="LANGFUSE_PUBLIC_KEY")
    secret_key: str = Field(default="", alias="LANGFUSE_SECRET_KEY")
    host: str = Field(default="https://us.cloud.langfuse.com", alias="LANGFUSE_HOST")

    @property
    def is_configured(self) -> bool:
        return bool(self.public_key and self.secret_key)


class BudgetConfig(BaseSettings):
    """Budget guard thresholds — master plan §8.1 BudgetGuard halt conditions."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    smoke_usd: Decimal = Field(default=Decimal("1.00"), alias="BUDGET_SMOKE_USD")
    seeded_usd: Decimal = Field(default=Decimal("5.00"), alias="BUDGET_SEEDED_USD")
    exploratory_usd: Decimal = Field(default=Decimal("10.00"), alias="BUDGET_EXPLORATORY_USD")
    per_day_usd: Decimal = Field(default=Decimal("25.00"), alias="BUDGET_PER_DAY_USD")
    halt_after_n_null_runs: int = Field(default=25, alias="BUDGET_HALT_AFTER_N_NULL_RUNS")
    null_run_spend_threshold_usd: Decimal = Field(
        default=Decimal("3.00"), alias="BUDGET_NULL_RUN_SPEND_THRESHOLD_USD"
    )
    per_attack_timeout_s: int = Field(default=60, alias="BUDGET_PER_ATTACK_TIMEOUT_S")
    target_error_rate_halt: float = Field(default=0.20, alias="BUDGET_TARGET_ERROR_RATE_HALT")

    @field_validator(
        "smoke_usd",
        "seeded_usd",
        "exploratory_usd",
        "per_day_usd",
        "null_run_spend_threshold_usd",
        mode="before",
    )
    @classmethod
    def _coerce_decimal(cls, v: object) -> Decimal:
        if isinstance(v, Decimal):
            return v
        return Decimal(str(v))


class AdapterConfig(BaseSettings):
    """Target adapter + allowlist — master plan §3 + AgDR-0002 (local-only)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    target_base_url: str = Field(default="http://localhost:8300", alias="TARGET_BASE_URL")
    target_https_base_url: str = Field(
        default="https://localhost:9300", alias="TARGET_HTTPS_BASE_URL"
    )
    copilot_sidecar_url: str = Field(default="http://localhost:8000", alias="COPILOT_SIDECAR_URL")
    copilot_gateway_path: str = Field(
        default="/interface/modules/custom_modules/oe-module-clinical-copilot",
        alias="COPILOT_GATEWAY_PATH",
    )
    openemr_admin_user: str = Field(default="admin", alias="OPENEMR_ADMIN_USER")
    openemr_admin_pass: str = Field(default="pass", alias="OPENEMR_ADMIN_PASS")
    sidecar_shared_secret: str = Field(default="", alias="SIDECAR_SHARED_SECRET")
    target_allowlist: list[str] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "host.docker.internal"],
        alias="TARGET_ALLOWLIST",
    )
    allow_browser_automation: bool = Field(default=False, alias="ALLOW_BROWSER_AUTOMATION")
    allow_target_fixes_push: bool = Field(default=False, alias="ALLOW_TARGET_FIXES_PUSH")

    @field_validator("target_allowlist", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> list[str]:
        if isinstance(v, str):
            return [h.strip() for h in v.split(",") if h.strip()]
        if isinstance(v, list):
            return [str(h).strip() for h in v if str(h).strip()]
        return []


class MainConfig(BaseSettings):
    """Top-level aggregated settings — singleton via get_settings()."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    redteam_provider: Literal["openrouter", "anthropic", "fireworks"] = Field(
        default="openrouter", alias="REDTEAM_PROVIDER"
    )
    platform_db_url: str = Field(
        default="sqlite:///./data/agentforge.sqlite", alias="PLATFORM_DB_URL"
    )
    agent_message_signing_secret: str = Field(default="", alias="AGENT_MESSAGE_SIGNING_SECRET")
    pricing_yml_freshness_days: int = Field(default=30, alias="PRICING_YML_FRESHNESS_DAYS")

    anthropic: AnthropicConfig = Field(default_factory=AnthropicConfig)
    openrouter: OpenRouterConfig = Field(default_factory=OpenRouterConfig)
    fireworks: FireworksConfig = Field(default_factory=FireworksConfig)
    langfuse: LangfuseConfig = Field(default_factory=LangfuseConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    adapter: AdapterConfig = Field(default_factory=AdapterConfig)


@lru_cache(maxsize=1)
def get_settings() -> MainConfig:
    """Lazy singleton accessor — do NOT instantiate at import time."""
    return MainConfig()
