"""PHI regex patterns — master plan §8.3 / §12.

Placeholders only. Phase 3 lands the real patterns (SSN / phone / DOB / MRN)
that mirror the Co-Pilot's `scrub_phi` matcher.
"""

from __future__ import annotations

import re
from typing import Final

SSN_RE: Final[re.Pattern[str]] = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
PHONE_RE: Final[re.Pattern[str]] = re.compile(r"\b\d{3}-\d{3}-\d{4}\b")
DOB_RE: Final[re.Pattern[str]] = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
MRN_RE: Final[re.Pattern[str]] = re.compile(r"\bMRN[-:]?\s?\d{4,}\b", re.IGNORECASE)

PATTERNS: Final[dict[str, re.Pattern[str]]] = {
    "SSN": SSN_RE,
    "PHONE": PHONE_RE,
    "DOB": DOB_RE,
    "MRN": MRN_RE,
}
