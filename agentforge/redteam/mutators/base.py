"""Mutator ABC — master plan §8.2."""

from __future__ import annotations

from abc import ABC, abstractmethod


class Mutator(ABC):
    """Base class for prompt mutators. Deterministic on `seed_int`."""

    name: str = "base"

    @abstractmethod
    def apply(self, prompt: str, seed_int: int) -> str:
        """Apply the mutation deterministically given `seed_int`."""
