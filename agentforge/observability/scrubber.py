"""PHI scrubber — master plan §12. Mirrors Co-Pilot scrub_phi.

Applies the same patterns as `agentforge.judge.deterministic.phi_patterns`.
"""

from __future__ import annotations

from agentforge.judge.deterministic.phi_patterns import PATTERNS

REPLACEMENTS: dict[str, str] = {
    "SSN": "[REDACTED-SSN]",
    "PHONE": "[REDACTED-PHONE]",
    "DOB": "[REDACTED-DOB]",
    "MRN": "[REDACTED-MRN]",
}


def scrub_phi(text: str) -> str:
    """Redact PHI tokens in `text`. Multi-layer; applies every pattern."""
    if not text:
        return text
    scrubbed = text
    for label, pattern in PATTERNS.items():
        replacement = REPLACEMENTS.get(label, "[REDACTED]")
        scrubbed = pattern.sub(replacement, scrubbed)
    return scrubbed
