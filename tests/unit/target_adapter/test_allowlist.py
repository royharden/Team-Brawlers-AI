"""Target allowlist guard — master plan §4 + AgDR-0002.

Out-of-scope hosts MUST raise `TargetNotAllowed`. In-allowlist hosts MUST pass.
"""

from __future__ import annotations

import pytest

from agentforge.target_adapter.allowlist import (
    TargetNotAllowed,
    is_allowed,
    require_allowed,
)


@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8300/healthz",
        "https://127.0.0.1/v1/copilot/answer",
        "http://host.docker.internal:8000/v1/extract/lab",
    ],
)
def test_allowlist_permits_local_hosts(url: str) -> None:
    assert is_allowed(url) is True
    require_allowed(url)  # should not raise


@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/x",
        "https://attacker.test:8080/y",
        "http://evil.host.docker.internal.attacker.com/z",
        "http://10.0.0.5/api",
    ],
)
def test_allowlist_rejects_out_of_scope_hosts(url: str) -> None:
    assert is_allowed(url) is False
    with pytest.raises(TargetNotAllowed):
        require_allowed(url)


@pytest.mark.unit
@pytest.mark.parametrize("url", ["", "not a url", "ftp://", "://nohost"])
def test_allowlist_rejects_malformed_input(url: str) -> None:
    assert is_allowed(url) is False
    with pytest.raises(TargetNotAllowed):
        require_allowed(url)
