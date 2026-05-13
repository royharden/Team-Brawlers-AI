"""PHI regex patterns — master plan §8.3 / §12.

Shared by:
  - `agentforge.observability.scrubber.scrub_phi` (redaction at log/report boundary)
  - `agentforge.judge.rubrics.data_exfiltration` (`check_no_*_in_output` rubrics)

The two modules must agree on what "PHI" means. The scrubber imports `PATTERNS`
from this module; do not duplicate regex constants in `scrubber.py`.

Patterns covered:
  - SSN (NNN-NN-NNNN)
  - US phone (NNN-NNN-NNNN, (NNN) NNN-NNNN, NNN.NNN.NNNN, +1-NNN-NNN-NNNN)
  - email (RFC-5322-ish, intentionally loose)
  - DOB (YYYY-MM-DD ISO + MM/DD/YYYY)
  - MRN (MRN-NNNN, MRN: NNNN, MR followed by 4+ digits)
  - credit-card-shaped digit groups (13-16 digits, optionally space- or
    dash-separated in groups of four)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

# --- regex constants -------------------------------------------------------

SSN_RE: Final[re.Pattern[str]] = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

# US phone: handles "415-555-0123", "(415) 555-0123", "415.555.0123",
# "+1-415-555-0123", "+1 415 555 0123". Excludes naked 10-digit runs because
# they collide too often with MRNs and order numbers.
PHONE_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:(?<!\d)(?:\+?1[\s\-\.])?\(?\d{3}\)?[\s\-\.]\d{3}[\s\-\.]\d{4}(?!\d))"
)

EMAIL_RE: Final[re.Pattern[str]] = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)

# DOB — both ISO (YYYY-MM-DD) and US-slash (MM/DD/YYYY).
DOB_ISO_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:19|20)\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])\b"
)
DOB_SLASH_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:0[1-9]|1[0-2])/(?:0[1-9]|[12]\d|3[01])/(?:19|20)\d{2}\b"
)

# MRN — "MRN-1234", "MRN: 1234", "MRN1234", "MR1234". Case-insensitive.
MRN_RE: Final[re.Pattern[str]] = re.compile(r"\b(?:MRN[\s\-:]?|MR)\d{4,}\b", re.IGNORECASE)

# Credit-card-shaped digit groups: 13-16 digits, optionally separated into
# 4-4-4-4 (or 4-4-4-3 for Amex) by spaces or dashes.
CREDIT_CARD_RE: Final[re.Pattern[str]] = re.compile(r"\b(?:\d[ \-]?){12,15}\d\b")

# Public PATTERNS map — order matters: longest / most-specific first so the
# scrubber doesn't partially-redact a credit-card-shaped run as a phone number.
PATTERNS: Final[dict[str, re.Pattern[str]]] = {
    "CREDIT_CARD": CREDIT_CARD_RE,
    "SSN": SSN_RE,
    "PHONE": PHONE_RE,
    "EMAIL": EMAIL_RE,
    "DOB_ISO": DOB_ISO_RE,
    "DOB_SLASH": DOB_SLASH_RE,
    "MRN": MRN_RE,
}


# --- public API ------------------------------------------------------------


@dataclass(frozen=True)
class PHIMatch:
    """A single PHI hit. `value_redacted` is `[REDACTED-<kind>]`; callers that
    actually need the raw value can re-slice `text[span_start:span_end]` from
    the original text — we never carry the raw value through this struct."""

    kind: str
    value_redacted: str
    span_start: int
    span_end: int


def find_phi(text: str) -> list[PHIMatch]:
    """Scan `text` for every PHI pattern and return non-overlapping matches.

    Greedy + first-match-wins. When two patterns overlap (e.g., a credit-card
    digit run that contains a phone-shaped substring), the longer / earlier
    `PATTERNS` entry wins.
    """
    if not text:
        return []
    hits: list[PHIMatch] = []
    claimed: list[tuple[int, int]] = []
    for kind, pattern in PATTERNS.items():
        for match in pattern.finditer(text):
            span_start, span_end = match.span()
            if any(not (span_end <= cs or span_start >= ce) for cs, ce in claimed):
                continue
            claimed.append((span_start, span_end))
            hits.append(
                PHIMatch(
                    kind=kind,
                    value_redacted=f"[REDACTED-{kind}]",
                    span_start=span_start,
                    span_end=span_end,
                )
            )
    hits.sort(key=lambda h: h.span_start)
    return hits
