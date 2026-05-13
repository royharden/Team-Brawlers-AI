"""Target fingerprint — master plan §8.1 (regression trigger on change)."""

from __future__ import annotations

import hashlib


def compute_fingerprint(
    url: str,
    healthz_hash: str,
    docker_image_tag: str,
    git_rev: str,
) -> str:
    """SHA-256 of (url, /healthz body hash, docker tag, git rev) — order-stable.

    Used by the orchestrator to detect when the target has changed and trigger
    the regression suite (master plan §13).
    """
    payload = "|".join([url.strip(), healthz_hash.strip(), docker_image_tag.strip(), git_rev.strip()])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
