"""HMAC signing for inter-agent messages — master plan §5.1 (AGENT_MESSAGE_SIGNING_SECRET).

Real implementation. Uses `hmac.compare_digest` for tamper-resistant verification.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from agentforge.config import get_settings


class InvalidSignature(Exception):
    """Raised when a message signature does not match its payload."""


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    """Serialize `payload` deterministically (sorted keys, no whitespace)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign(payload: dict[str, Any], secret: str | None = None) -> str:
    """Return the hex HMAC-SHA256 signature of `payload`."""
    key = (secret if secret is not None else get_settings().agent_message_signing_secret).encode(
        "utf-8"
    )
    if not key:
        raise InvalidSignature("AGENT_MESSAGE_SIGNING_SECRET is empty; cannot sign")
    return hmac.new(key, _canonical_bytes(payload), hashlib.sha256).hexdigest()


def verify(payload: dict[str, Any], signature: str, secret: str | None = None) -> None:
    """Raise `InvalidSignature` if `signature` does not match `payload`."""
    expected = sign(payload, secret=secret)
    if not hmac.compare_digest(expected, signature):
        raise InvalidSignature("HMAC signature mismatch — message may have been tampered")
