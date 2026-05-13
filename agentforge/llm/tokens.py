"""Shared `TokenUsage` dataclass for the per-call cost-ledger path.

Originally defined in :mod:`agentforge.llm.anthropic_clients` (AgDR-0019);
sub-plan Next05 §4 promoted it to a neutral module so the Red Team
clients (OpenRouter + OpenAI direct) can share the same shape without
either importing the other's SDK or violating the provider-isolation
lint.

`agentforge.llm.anthropic_clients.TokenUsage` is re-exported from here
for back-compat — every pre-Next05 import path keeps working.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TokenUsage:
    """Per-call token + model record reported by an LLM SDK.

    All four Anthropic wrappers (AgDR-0019), the OpenRouter Red Team
    client (sub-plan Next05 §4), and the OpenAI direct fallback client
    (AgDR-0024 + Next05 §4) populate `self.last_usage` on each successful
    call. Consumers must defensively handle `None` (failed call /
    pre-population state).
    """

    input_tokens: int
    output_tokens: int
    model: str


__all__ = ["TokenUsage"]
