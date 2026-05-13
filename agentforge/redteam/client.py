"""Red Team client Protocol — master plan §8.2 + AgDR-0013.

Provider-neutral surface every Red Team backend (OpenRouter, Anthropic
fallback, future Fireworks) implements. The RedTeamAgent depends on this
Protocol; concrete implementations live in `openrouter_client.py` and
`anthropic_client.py`.

The Protocol intentionally lives in a separate module from any concrete
client so:
- The Protocol can be imported without importing any provider SDK.
- The CI per-class-import lint (`tests/unit/redteam/test_provider_isolation.py`)
  stays satisfied: `openai` is only imported by `openrouter_client.py`,
  `anthropic` is only imported by `anthropic_client.py`.
- The Protocol name doesn't carry vendor lineage.
"""

from __future__ import annotations

from typing import Any, Protocol

from agentforge.judge.deterministic.refusal_taxonomy import RefusalInfo


class RedTeamClient(Protocol):
    """Anything the RedTeamAgent.generate() / .escalate() path can call.

    Returns the paraphrased text plus an optional RefusalInfo if the model
    refused the request (or emitted a known refusal marker).
    """

    def paraphrase(
        self, seed: dict[str, Any], current_prompt: str
    ) -> tuple[str, RefusalInfo | None]: ...
