"""Langfuse client wrapper — master plan §12.

Real implementation:
    - Lazy SDK instantiation when all three env vars are set.
    - `LANGFUSE_DISABLED` no-op mode when keys are absent.
    - `trace(...)` context manager wrapping a Langfuse span.
    - `record_llm_call(...)` emits a generation event.
    - `flush()` forwards to the SDK on shutdown.
    - PHI scrubbing applied to every payload BEFORE it leaves this module.

Tests inject a fake `_sdk_factory` to capture payloads without network.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from decimal import Decimal
from typing import Any

from loguru import logger

from agentforge.config import get_settings
from agentforge.observability.scrubber import scrub_phi, scrub_phi_in_obj


class _NullSpan:
    """No-op span returned in disabled mode (and as a fallback)."""

    def set_output(self, output: Any) -> None:
        return None

    def end(self) -> None:
        return None


class LangfuseClient:
    """Thin wrapper around `langfuse.Langfuse` with PHI scrubbing baked in.

    All inputs/outputs/metadata pass through `scrub_phi_in_obj` before hitting
    the SDK. The wrapper is safe to instantiate even when Langfuse env vars
    are missing — it operates as a no-op in that case.
    """

    def __init__(
        self,
        *,
        sdk_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._cfg = get_settings().langfuse
        self._enabled = self._cfg.is_configured and bool(self._cfg.host)
        self._sdk: Any | None = None

        if not self._enabled:
            logger.warning("Langfuse keys missing — LANGFUSE_DISABLED mode (no-op tracing)")
            return

        try:
            factory = sdk_factory or _default_sdk_factory
            self._sdk = factory(
                public_key=self._cfg.public_key,
                secret_key=self._cfg.secret_key,
                host=self._cfg.host,
            )
        except Exception as exc:
            logger.error("Langfuse SDK init failed: {} — falling back to no-op", exc)
            self._enabled = False
            self._sdk = None

    # ---- public API ----------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    @contextmanager
    def trace(
        self,
        name: str,
        input: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> Iterator[Any]:
        """Context manager that opens a Langfuse trace span.

        On exit, records duration and any output set via `span.set_output(...)`.
        Yields a `_NullSpan` in disabled mode so callers can write
        `with client.trace(...) as span: ...` unconditionally.
        """
        if not self._enabled or self._sdk is None:
            yield _NullSpan()
            return

        scrubbed_input = scrub_phi_in_obj(input)
        scrubbed_meta = scrub_phi_in_obj(metadata or {})
        start = time.monotonic()
        span: Any
        try:
            span = self._sdk.trace(name=name, input=scrubbed_input, metadata=scrubbed_meta)
        except Exception as exc:
            logger.error("Langfuse trace open failed: {}", exc)
            yield _NullSpan()
            return

        # Capture user-supplied output for end-time emission.
        captured: dict[str, Any] = {"output": None}
        wrapper = _SpanProxy(span, captured)
        try:
            yield wrapper
        finally:
            duration_ms = int((time.monotonic() - start) * 1000)
            try:
                output_scrubbed = scrub_phi_in_obj(captured["output"])
                end_fn = getattr(span, "end", None)
                if callable(end_fn):
                    end_fn(output=output_scrubbed, duration_ms=duration_ms)
                else:
                    set_output = getattr(span, "set_output", None)
                    if callable(set_output):
                        set_output(output_scrubbed)
            except Exception as exc:
                logger.error("Langfuse trace close failed: {}", exc)

    def record_llm_call(
        self,
        *,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: Decimal | float,
        latency_ms: int,
        error: str | None = None,
    ) -> None:
        """Emit a Langfuse generation event for one LLM call."""
        if not self._enabled or self._sdk is None:
            return

        payload: dict[str, Any] = {
            "model": model,
            "usage": {
                "input": int(input_tokens),
                "output": int(output_tokens),
            },
            "metadata": {
                "cost_usd": str(Decimal(str(cost_usd))),
                "latency_ms": int(latency_ms),
            },
        }
        if error is not None:
            payload["error"] = scrub_phi(str(error))

        try:
            gen_fn = getattr(self._sdk, "generation", None)
            if callable(gen_fn):
                gen_fn(**payload)
            else:
                # Older SDKs name it `create_generation` — be tolerant.
                alt = getattr(self._sdk, "create_generation", None)
                if callable(alt):
                    alt(**payload)
        except Exception as exc:
            logger.error("Langfuse generation emit failed: {}", exc)

    def flush(self) -> None:
        """Forward to SDK; called at process shutdown."""
        if not self._enabled or self._sdk is None:
            return
        try:
            flush_fn = getattr(self._sdk, "flush", None)
            if callable(flush_fn):
                flush_fn()
        except Exception as exc:
            logger.error("Langfuse flush failed: {}", exc)


class _SpanProxy:
    """Thin proxy that captures `set_output` calls for the context manager."""

    def __init__(self, inner: Any, captured: dict[str, Any]) -> None:
        self._inner = inner
        self._captured = captured

    def set_output(self, output: Any) -> None:
        self._captured["output"] = output
        set_output = getattr(self._inner, "set_output", None)
        if callable(set_output):
            try:
                set_output(scrub_phi_in_obj(output))
            except Exception as exc:
                logger.error("Langfuse set_output failed: {}", exc)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _default_sdk_factory(**kwargs: Any) -> Any:
    """Real Langfuse SDK constructor — lazy import."""
    from langfuse import Langfuse  # type: ignore[import-not-found]

    return Langfuse(**kwargs)
