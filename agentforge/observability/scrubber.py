"""PHI scrubber — master plan §12.

Real PHI regex set covering SSN, US phone (multiple formats), email, DOB
(ISO + US), MRN-like patterns, credit-card-shaped digits, and a generic
9-11 digit "long number" pattern that preserves the last 4.

Public API:
    - `scrub_phi(text: str) -> str`
    - `scrub_phi_in_obj(obj: Any) -> Any` (recurses dict/list/str)

Used by the Langfuse client before sending payloads, and by the Documentation
agent before persisting evidence.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Final

# --- Regex set ----------------------------------------------------------------

# Order matters: more-specific patterns first.
_SSN_RE: Final[re.Pattern[str]] = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

# US phone — handles 555-555-5555, (555) 555-5555, 555.555.5555, 5555555555,
# and +1 555 555 5555 forms.
_PHONE_RE: Final[re.Pattern[str]] = re.compile(
    r"""
    (?<!\d)                                 # not preceded by another digit
    (?:\+?1[\s.\-]?)?                       # optional country code
    (?:
        \(\d{3}\)\s?\d{3}[\s.\-]?\d{4}      # (555) 555-5555
        |
        \d{3}[\s.\-]\d{3}[\s.\-]\d{4}        # 555-555-5555 or 555.555.5555
        |
        \d{10}                               # 5555555555
    )
    (?!\d)                                  # not followed by another digit
    """,
    re.VERBOSE,
)

_EMAIL_RE: Final[re.Pattern[str]] = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)

# DOB: ISO (YYYY-MM-DD) — guard against capturing inside a longer digit run.
_DOB_ISO_RE: Final[re.Pattern[str]] = re.compile(
    r"(?<!\d)(?:19|20)\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])(?!\d)"
)
# DOB: US (MM/DD/YYYY or M/D/YYYY).
_DOB_US_RE: Final[re.Pattern[str]] = re.compile(
    r"(?<!\d)(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12]\d|3[01])/(?:19|20)\d{2}(?!\d)"
)

# MRN-like patterns: "MRN-12345", "MRN: 12345", "MR12345".
_MRN_DASH_RE: Final[re.Pattern[str]] = re.compile(
    r"\bMRN[-:]?\s?\d{4,}\b", re.IGNORECASE
)
_MRN_PREFIX_RE: Final[re.Pattern[str]] = re.compile(r"\bMR\d{4,}\b")

# Credit-card-shaped digit groups: 13-19 digit runs, optionally split by spaces
# or dashes in 4-digit groups. (Visa/MC/Amex/Discover are all covered by the
# 13-19 length window.)
_CC_RE: Final[re.Pattern[str]] = re.compile(
    r"""
    (?<!\d)
    (?:
        \d{4}[\s\-]\d{4}[\s\-]\d{4}[\s\-]\d{1,4}    # 4-4-4-4 (or -1 to -4)
        |
        \d{13,19}                                   # solid run
    )
    (?!\d)
    """,
    re.VERBOSE,
)

# Generic "long number" — 9-11 digits, not preceded/followed by digits.
# Keeps the LAST 4 visible: ****-1234.
_LONG_DIGITS_RE: Final[re.Pattern[str]] = re.compile(r"(?<!\d)(\d{5,7})(\d{4})(?!\d)")


REPLACEMENTS: Final[dict[str, str]] = {
    "SSN": "[REDACTED-SSN]",
    "PHONE": "[REDACTED-PHONE]",
    "EMAIL": "[REDACTED-EMAIL]",
    "DOB": "[REDACTED-DOB]",
    "MRN": "[REDACTED-MRN]",
    "CC": "[REDACTED-CC]",
    "DIGITS": "[REDACTED-DIGITS]",
}


def _replace_long_digits(match: re.Match[str]) -> str:
    """Preserve last 4 digits as ****-1234."""
    last4 = match.group(2)
    return f"****-{last4}"


# Ordered pipeline. Each entry: (label, pattern, replacement-or-callable).
_PIPELINE: Final[list[tuple[str, re.Pattern[str], str | Any]]] = [
    ("SSN", _SSN_RE, REPLACEMENTS["SSN"]),
    ("CC", _CC_RE, REPLACEMENTS["CC"]),
    ("PHONE", _PHONE_RE, REPLACEMENTS["PHONE"]),
    ("EMAIL", _EMAIL_RE, REPLACEMENTS["EMAIL"]),
    ("DOB_ISO", _DOB_ISO_RE, REPLACEMENTS["DOB"]),
    ("DOB_US", _DOB_US_RE, REPLACEMENTS["DOB"]),
    ("MRN_DASH", _MRN_DASH_RE, REPLACEMENTS["MRN"]),
    ("MRN_PREFIX", _MRN_PREFIX_RE, REPLACEMENTS["MRN"]),
    ("LONG_DIGITS", _LONG_DIGITS_RE, _replace_long_digits),
]


def scrub_phi(text: str) -> str:
    """Redact PHI tokens in `text`. Multi-layer; applies every pattern in order.

    Returns the original value unchanged for non-string / empty inputs.
    """
    if not text or not isinstance(text, str):
        return text
    scrubbed = text
    for _label, pattern, replacement in _PIPELINE:
        if callable(replacement):
            scrubbed = pattern.sub(replacement, scrubbed)
        else:
            scrubbed = pattern.sub(replacement, scrubbed)
    return scrubbed


def scrub_phi_in_obj(obj: Any) -> Any:
    """Recursively scrub PHI inside dicts / lists / strings.

    Non-container, non-string values are returned unchanged (e.g. int, float,
    bool, None, datetime). Tuples are converted to lists to keep things simple;
    callers that need tuple-preservation should serialize first.
    """
    if isinstance(obj, str):
        return scrub_phi(obj)
    if isinstance(obj, Mapping):
        return {k: scrub_phi_in_obj(v) for k, v in obj.items()}
    # bytes and bytearray are Sequence but should not be recursed into.
    if isinstance(obj, (bytes, bytearray)):
        return obj
    if isinstance(obj, Sequence):
        return [scrub_phi_in_obj(v) for v in obj]
    return obj
