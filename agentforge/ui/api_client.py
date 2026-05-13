"""httpx-based thin client → FastAPI app — master plan §4."""

from __future__ import annotations

from typing import Any

import httpx


class APIClient:
    """Synchronous httpx client that talks to the AgentForge FastAPI app."""

    def __init__(self, base_url: str = "http://localhost:8001") -> None:
        self.base_url = base_url
        self._client: httpx.Client = httpx.Client(base_url=base_url, timeout=10.0)

    def healthz(self) -> dict[str, Any]:
        resp = self._client.get("/healthz")
        resp.raise_for_status()
        return resp.json()
