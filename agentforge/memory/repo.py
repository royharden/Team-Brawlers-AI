"""Repository pattern over `memory.models` — master plan §5.

Thin SQLAlchemy facade. Agents call repo methods rather than touching
sessions directly so that persistence is testable in isolation and the
schema can evolve without rippling through agent code.

Phase 3 adds:
    - `MemoryRepo.insert_vuln_report` — Documentation Agent writes VRs.
    - `MemoryRepo.insert_vulnerability_class` — registers a new class.
    - `MemoryRepo.insert_regression_case` — paired with the JSON file the
      RegressionCurator writes.
    - `MemoryRepo.upsert_vulnerability_class_by_dedupe_key` — used by the
      `VulnerabilityClassIndex.register` semantics when going through the
      repo instead of touching the session directly.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from agentforge.memory.models import (
    RegressionCase,
    VulnerabilityClass,
    VulnReport,
)


class MemoryRepo:
    """Thin repository facade. Each Phase 1 method delegates to a SQLAlchemy session."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def save_run(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("Phase 1 — not yet wired")

    # --- Vulnerability classes ------------------------------------------------

    def insert_vulnerability_class(
        self,
        *,
        id: str,
        dedupe_key_sha256: str,
        category: str,
        target_endpoint: str,
        normalized_objective: str,
        first_seen_at: datetime,
        status: str = "open",
    ) -> str:
        session = self._session_factory()
        try:
            row = VulnerabilityClass(
                id=id,
                dedupe_key_sha256=dedupe_key_sha256,
                category=category,
                target_endpoint=target_endpoint,
                normalized_objective=normalized_objective,
                first_seen_at=first_seen_at,
                status=status,
            )
            session.add(row)
            session.commit()
            return id
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # --- VR reports -----------------------------------------------------------

    def insert_vuln_report(
        self,
        *,
        id: str,
        vr_id: str,
        vulnerability_class_id: str,
        severity: str,
        defcon: int,
        safety_score_0_100: int,
        owasp_llm10: list[str],
        owasp_agentic: list[str],
        avid: list[str],
        nist_ai_rmf: list[str],
        status: str,
        target_fingerprint_at_discovery: str,
        written_at: datetime,
        content_markdown: str,
        content_html: str,
        fix_status: str = "unfixed",
    ) -> str:
        session = self._session_factory()
        try:
            row = VulnReport(
                id=id,
                vr_id=vr_id,
                vulnerability_class_id=vulnerability_class_id,
                severity=severity,
                defcon=defcon,
                safety_score_0_100=safety_score_0_100,
                owasp_llm10_json=json.dumps(owasp_llm10),
                owasp_agentic_json=json.dumps(owasp_agentic),
                avid_json=json.dumps(avid),
                nist_ai_rmf_json=json.dumps(nist_ai_rmf),
                status=status,
                fix_status=fix_status,
                target_fingerprint_at_discovery=target_fingerprint_at_discovery,
                written_at=written_at,
                content_markdown=content_markdown,
                content_html=content_html,
            )
            session.add(row)
            session.commit()
            return vr_id
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # --- Regression cases -----------------------------------------------------

    def insert_regression_case(
        self,
        *,
        id: str,
        vr_id: str,
        what_bug_this_catches: str,
        case_json: str,
    ) -> str:
        session = self._session_factory()
        try:
            row = RegressionCase(
                id=id,
                vr_id=vr_id,
                what_bug_this_catches=what_bug_this_catches,
                case_json=case_json,
            )
            session.add(row)
            session.commit()
            return id
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


__all__ = ["MemoryRepo"]
