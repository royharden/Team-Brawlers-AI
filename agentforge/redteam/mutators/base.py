"""Mutator ABC + MutatorStack — master plan §8.2."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Mutator(Protocol):
    """Deterministic prompt mutator. Pure: no I/O, no LLM."""

    id: str

    def apply(self, prompt: str, seed_int: int) -> str: ...
    def applicable_to(self, seed: dict[str, Any]) -> bool: ...


class MutatorStack:
    """Composes a sequence of registered mutators by id.

    `compose` applies the requested mutators in order, silently skipping any
    that are not registered or whose `applicable_to(seed)` returns False.
    """

    def __init__(self, mutators: Sequence[Mutator]) -> None:
        self._by_id: dict[str, Mutator] = {m.id: m for m in mutators}

    @property
    def registered_ids(self) -> list[str]:
        return list(self._by_id.keys())

    def compose(
        self, seed: dict[str, Any], mutator_ids: Sequence[str], seed_int: int
    ) -> tuple[str, list[str]]:
        """Apply requested mutators in order; return (final_prompt, applied_ids).

        Unknown ids and non-applicable mutators are skipped silently and are
        not recorded in `applied_ids`. The base prompt is taken from
        `seed["prompt"]` if present, else an empty string.
        """
        prompt = str(seed.get("prompt", ""))
        applied: list[str] = []
        for mid in mutator_ids:
            mutator = self._by_id.get(mid)
            if mutator is None:
                continue
            if not mutator.applicable_to(seed):
                continue
            prompt = mutator.apply(prompt, seed_int)
            applied.append(mid)
        return prompt, applied
