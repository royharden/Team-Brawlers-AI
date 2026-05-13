"""Documentation Agent — master plan §8.4.

The Documentation Agent ONLY consumes `external_final` verdicts. Internal
progress verdicts are observability signals for the Red Team — they MUST NOT
produce vulnerability reports. Step 1 of `write_report` enforces this
invariant; misuse raises immediately.

Pipeline (master plan §8.4):
    1.  Layer enforcement.
    2.  Compute dedupe key from (category, endpoint, seed_id, response_sig).
    3.  Lookup or register the VulnerabilityClass.
    4.  Allocate next VR-#### via atomic file counter at reports/.vr_counter.
    5.  Tag taxonomies via Tagger.
    6.  Read severity / defcon / safety_score from the ExternalVerdict.
    7.  Status: High+ → awaiting_approval, else draft. Append notifier line.
    8.  Body: LLM polish if client injected, else template-only with marker.
    9.  PHI-scrub every text field.
    10. Render markdown + HTML to reports/VR-####-<slug>.{md,html}.
    11. Emit regression case (refuses on empty what_bug_this_catches).
    12. Persist to vuln_reports / vulnerability_classes / regression_cases
        via repo (does NOT touch SQLAlchemy directly).
    13. Return the VulnerabilityReport.

The `ExternalVerdict` type is owned by `agentforge.judge.external_final`.
We import it lazily (TYPE_CHECKING) and accept duck-typed values at runtime
so the Documentation Agent does not import-couple to the Judge package at
load time.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, Field

from agentforge.documentation.prompts import (
    DOC_SYSTEM_PROMPT,
    DOC_USER_PROMPT_TEMPLATE,
)
from agentforge.documentation.regression_curator import RegressionCurator
from agentforge.documentation.tagger import Tagger
from agentforge.documentation.vulnerability_class import (
    VulnerabilityClassIndex,
    canonical_json,
    response_signature,
)
from agentforge.memory.repo import MemoryRepo
from agentforge.memory.schemas import AdapterResponse, MutatedAttack
from agentforge.observability.scrubber import scrub_phi

if TYPE_CHECKING:  # pragma: no cover — import only for typing
    from agentforge.judge.external_final import ExternalVerdict  # noqa: F401


_TEMPLATE_DIR = Path(__file__).parent / "templates"
_SLUG_NON_WORD = re.compile(r"[^a-z0-9]+")


# --- Client protocol ----------------------------------------------------------


class DocAnthropicClient(Protocol):
    """Anthropic SDK wrapper for the Documentation Agent. Distinct from the
    Red Team and Judge clients so each can be substituted independently.
    """

    def write_report_body(self, system: str, user: str) -> str: ...


# --- Output type --------------------------------------------------------------


class VulnerabilityReport(BaseModel):
    """The Documentation Agent's return value. Mirrors the `vuln_reports` row
    plus the rendered markdown / HTML contents.
    """

    vr_id: str
    vulnerability_class_id: str
    category: str
    severity: Literal["Critical", "High", "Medium", "Low", "Info"]
    defcon: int
    safety_score_0_100: int
    owasp_llm_top_10: list[str] = Field(default_factory=list)
    owasp_agentic_top_10: list[str] = Field(default_factory=list)
    avid: list[str] = Field(default_factory=list)
    nist_ai_rmf: list[str] = Field(default_factory=list)
    status: Literal[
        "draft",
        "open",
        "awaiting_approval",
        "fix_in_progress",
        "fixed",
        "false_positive",
    ]
    target_fingerprint_at_discovery: str
    content_markdown: str
    content_html: str
    written_at: datetime
    run_id: str


# --- Agent --------------------------------------------------------------------


_HIGH_OR_ABOVE = {"Critical", "High"}


class DocumentationAgent:
    """Writes vulnerability reports. ONLY consumes external_final verdicts."""

    def __init__(
        self,
        anthropic_client: DocAnthropicClient | None,
        vc_index: VulnerabilityClassIndex,
        tagger: Tagger,
        regression_curator: RegressionCurator,
        reports_dir: Path,
        repo: MemoryRepo | None = None,
        vr_counter_path: Path | None = None,
        notifier_queue_path: Path | None = None,
        scrubber_fn: Callable[[str], str] = scrub_phi,
    ) -> None:
        self._client = anthropic_client
        self._vc_index = vc_index
        self._tagger = tagger
        self._curator = regression_curator
        self._repo = repo
        self._scrubber = scrubber_fn
        self._reports_dir = Path(reports_dir)
        self._reports_dir.mkdir(parents=True, exist_ok=True)
        self._vr_counter_path = (
            Path(vr_counter_path)
            if vr_counter_path is not None
            else self._reports_dir / ".vr_counter"
        )
        # Default notifier queue lives under data/.
        if notifier_queue_path is None:
            self._notifier_queue_path = Path("data") / "notifier_queue.jsonl"
        else:
            self._notifier_queue_path = Path(notifier_queue_path)
        self._notifier_queue_path.parent.mkdir(parents=True, exist_ok=True)
        self._jinja = Environment(
            loader=FileSystemLoader(str(_TEMPLATE_DIR)),
            autoescape=select_autoescape(enabled_extensions=("html",)),
            trim_blocks=False,
            lstrip_blocks=False,
        )

    # ------------------------------------------------------------------ utils

    def _allocate_vr_id(self) -> str:
        """Atomic monotonic counter at reports/.vr_counter.

        Reads the current int, increments, writes back via temp-file rename.
        Format: f"VR-{n:04d}".
        """
        path = self._vr_counter_path
        if path.exists():
            try:
                current = int(path.read_text(encoding="utf-8").strip() or "0")
            except ValueError:
                current = 0
        else:
            current = 0
        next_n = current + 1
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(str(next_n), encoding="utf-8")
        os.replace(tmp, path)
        return f"VR-{next_n:04d}"

    @staticmethod
    def _slugify(*parts: str) -> str:
        joined = "-".join(p for p in parts if p)
        slug = _SLUG_NON_WORD.sub("-", joined.lower()).strip("-")
        return slug or "report"

    def _scrub_text(self, text: str) -> str:
        if not isinstance(text, str):
            return text
        return self._scrubber(text)

    def _append_notifier(self, vr_id: str, severity: str) -> None:
        line = json.dumps(
            {
                "vr_id": vr_id,
                "severity": severity,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
        )
        with self._notifier_queue_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    @staticmethod
    def _verdict_attr(verdict: Any, name: str, default: Any = None) -> Any:
        """Duck-typed accessor for `ExternalVerdict` fields."""
        if hasattr(verdict, name):
            return getattr(verdict, name)
        if isinstance(verdict, dict):
            return verdict.get(name, default)
        return default

    # ------------------------------------------------------------- pipeline

    def write_report(
        self,
        *,
        attack: MutatedAttack,
        request: dict[str, Any],
        response: AdapterResponse,
        verdict: Any,  # ExternalVerdict — lazy-typed to avoid import-time cycle
        seed: dict[str, Any],
        target_fingerprint: str,
        run_id: str,
    ) -> VulnerabilityReport:
        # 1) Layer enforcement. Internal-judge verdicts MUST NOT produce VRs.
        layer = self._verdict_attr(verdict, "layer")
        if layer != "external_final":
            raise ValueError(
                "DocumentationAgent only consumes external_final verdicts"
            )

        # 2) Dedupe key from (category, endpoint, seed_id, response_sig).
        endpoint = request.get("endpoint", "unknown") if isinstance(request, dict) else "unknown"
        seed_id = seed.get("id", attack.seed_id) if isinstance(seed, dict) else attack.seed_id
        resp_sig = response_signature(response)
        resp_sig_hash = hashlib.sha256(resp_sig.encode("utf-8")).hexdigest()
        dedupe_key = VulnerabilityClassIndex.dedupe_key(
            attack.category, endpoint, seed_id, resp_sig_hash
        )

        # 3) Lookup or register the VulnerabilityClass.
        vc = self._vc_index.lookup(dedupe_key)
        if vc is None:
            vc = self._vc_index.register(
                category=attack.category,
                target_endpoint=endpoint,
                seed_id=seed_id,
                response_signature=resp_sig_hash,
            )
        vc_id = vc.id

        # 4) Allocate next VR-####.
        vr_id = self._allocate_vr_id()

        # 5) Tag.
        tags = self._tagger.tag(attack.category)

        # 6) Pull severity / defcon / safety_score from the ExternalVerdict.
        severity = self._verdict_attr(verdict, "severity", "Medium")
        defcon = int(self._verdict_attr(verdict, "defcon", 3))
        safety_score_0_100 = int(self._verdict_attr(verdict, "safety_score_0_100", 0))
        rationale = self._verdict_attr(verdict, "rationale", "")
        outcome = self._verdict_attr(verdict, "outcome", "fail")

        # 7) Status + notifier queue.
        status: Literal[
            "draft",
            "open",
            "awaiting_approval",
            "fix_in_progress",
            "fixed",
            "false_positive",
        ] = "awaiting_approval" if severity in _HIGH_OR_ABOVE else "draft"
        self._append_notifier(vr_id, severity)

        # 8) Body — LLM polish or template-only stub.
        taxonomy_block = (
            f"- OWASP LLM Top 10: {', '.join(tags.owasp_llm_top_10) or '—'}\n"
            f"- OWASP Agentic Top 10: {', '.join(tags.owasp_agentic_top_10) or '—'}\n"
            f"- AVID: {', '.join(tags.avid) or '—'}\n"
            f"- NIST AI RMF: {', '.join(tags.nist_ai_rmf) or '—'}"
        )
        attack_prompt_quoted = self._scrub_text(attack.rendered_prompt or "")
        target_response_quoted = self._scrub_text(response.body_text or "")
        expected_safe_behavior = seed.get("expected_safe_behavior", "")
        evidence_block = (
            f"attempt_id={attack.attack_id}\n"
            f"trace_id={request.get('trace_id', '') if isinstance(request, dict) else ''}\n"
            f"judge_verdict={outcome} :: {self._scrub_text(rationale)[:300]}"
        )

        clinical_impact = ""
        observed = ""
        expected = ""
        remediation: list[str] = []
        residual_risk = ""
        used_llm = False

        if self._client is not None:
            user_prompt = DOC_USER_PROMPT_TEMPLATE.format(
                vr_id=vr_id,
                category=attack.category,
                severity=severity,
                defcon=defcon,
                safety_score=safety_score_0_100,
                taxonomy_block=taxonomy_block,
                attack_prompt_quoted=attack_prompt_quoted,
                target_response_quoted=target_response_quoted,
                expected_safe_behavior=expected_safe_behavior,
                evidence_block=evidence_block,
            )
            try:
                body = self._client.write_report_body(DOC_SYSTEM_PROMPT, user_prompt)
                used_llm = True
                clinical_impact, observed, expected, remediation, residual_risk = (
                    self._parse_llm_body(body)
                )
            except Exception as exc:  # pragma: no cover — defensive
                clinical_impact = (
                    f"<!-- DRAFT_BODY: needs LLM polish (client error: {exc!r}) -->"
                )

        if not used_llm:
            # Template-only fallback with explicit draft marker.
            clinical_impact = (
                "<!-- DRAFT_BODY: needs LLM polish -->\n"
                f"Confirmed exploit in `{attack.category}`. The target produced "
                "a response that violates the expected safe behavior; manual "
                "review required before this section is published."
            )
            observed = (
                "Target response (PHI-scrubbed): "
                f"{target_response_quoted[:500] or '(empty)'}"
            )
            expected = expected_safe_behavior or "(see seed.expected_safe_behavior)"
            remediation = [
                "Block the offending input pattern at the prompt-construction layer.",
                "Add a deterministic rubric (or strengthen an existing one) to detect this output shape.",
                f"Add the regression case `evals/regression/{vr_id}.json` to the CI gate.",
            ]
            residual_risk = (
                "Until the fix lands, the exploit remains reproducible. The "
                "regression case will continue to fail (`expected_outcome: fail`)."
            )

        # 9) Final PHI scrub on every text field that goes into the report.
        clinical_impact = self._scrub_text(clinical_impact)
        observed = self._scrub_text(observed)
        expected = self._scrub_text(expected)
        remediation = [self._scrub_text(b) for b in remediation]
        residual_risk = self._scrub_text(residual_risk)

        # 10) Render markdown + HTML.
        body_text_scrubbed = self._scrub_text(response.body_text or "")
        http_block = (
            f"POST {endpoint} HTTP/1.1\n\n"
            f"{canonical_json(scrub_phi_obj_dict(request))[:1024]}\n\n"
            f"Response (200):\n{body_text_scrubbed[:2048]}"
        )

        ctx = {
            "vr": {
                "vr_id": vr_id,
                "severity": severity,
                "defcon": defcon,
                "safety_score_0_100": safety_score_0_100,
                "owasp_llm_top_10": tags.owasp_llm_top_10,
                "owasp_agentic_top_10": tags.owasp_agentic_top_10,
                "avid": tags.avid,
                "nist_ai_rmf": tags.nist_ai_rmf,
                "vulnerability_class_id": vc_id,
                "status": status,
                "target_fingerprint_at_discovery": target_fingerprint,
                "run_id": run_id,
            },
            "category": attack.category,
            "severity": severity,
            "clinical_impact": clinical_impact,
            "http_block": http_block,
            "observed": observed,
            "expected": expected,
            "remediation": remediation,
            "residual_risk": residual_risk,
            "trace_id": request.get("trace_id", "") if isinstance(request, dict) else "",
            "attempt_id": attack.attack_id,
            "judge_verdict_summary": f"{outcome} :: {self._scrub_text(rationale)[:300]}",
        }

        md_template = self._jinja.get_template("report_v1.md.j2")
        html_template = self._jinja.get_template("report_v1.html.j2")
        content_markdown = md_template.render(**ctx)
        content_html = html_template.render(**ctx)

        slug = self._slugify(attack.category, seed_id)
        md_path = self._reports_dir / f"{vr_id}-{slug}.md"
        html_path = self._reports_dir / f"{vr_id}-{slug}.html"
        md_path.write_text(content_markdown, encoding="utf-8")
        html_path.write_text(content_html, encoding="utf-8")

        # 11) Emit the regression case.
        what_bug_this_catches = (
            seed.get("what_bug_this_catches", "").strip()
            if isinstance(seed, dict)
            else ""
        )
        if not what_bug_this_catches:
            # Derive a non-empty fallback from the seed + rubric outcome. Empty
            # is still illegal (RegressionCurator will refuse), but most seeds
            # carry this field already.
            what_bug_this_catches = (
                f"Catches regression of {attack.category} exploit "
                f"({seed_id}) — verdict={outcome}"
            )
        self._curator.emit_case(
            vr_id=vr_id,
            seed=seed if isinstance(seed, dict) else {},
            attack=attack,
            expected_safe_behavior=expected_safe_behavior,
            target_fingerprint=target_fingerprint,
            run_id=run_id,
            what_bug_this_catches=what_bug_this_catches,
        )

        written_at = datetime.now(timezone.utc)

        # 12) Persist through the repo (if injected).
        if self._repo is not None:
            try:
                self._repo.insert_vuln_report(
                    id=str(uuid.uuid4()),
                    vr_id=vr_id,
                    vulnerability_class_id=vc_id,
                    severity=severity,
                    defcon=defcon,
                    safety_score_0_100=safety_score_0_100,
                    owasp_llm10=tags.owasp_llm_top_10,
                    owasp_agentic=tags.owasp_agentic_top_10,
                    avid=tags.avid,
                    nist_ai_rmf=tags.nist_ai_rmf,
                    status=status,
                    target_fingerprint_at_discovery=target_fingerprint,
                    written_at=written_at,
                    content_markdown=content_markdown,
                    content_html=content_html,
                )
                self._repo.insert_regression_case(
                    id=str(uuid.uuid4()),
                    vr_id=vr_id,
                    what_bug_this_catches=what_bug_this_catches,
                    case_json=json.dumps(
                        {
                            "vr_id": vr_id,
                            "category": attack.category,
                            "seed_id": seed_id,
                        }
                    ),
                )
            except Exception:
                # The filesystem artifacts are already written and considered
                # the primary record. Persistence failures bubble for tests
                # that wire a repo; production deploys retry via the orchestrator.
                raise

        # 13) Return.
        return VulnerabilityReport(
            vr_id=vr_id,
            vulnerability_class_id=vc_id,
            category=attack.category,
            severity=severity,
            defcon=defcon,
            safety_score_0_100=safety_score_0_100,
            owasp_llm_top_10=tags.owasp_llm_top_10,
            owasp_agentic_top_10=tags.owasp_agentic_top_10,
            avid=tags.avid,
            nist_ai_rmf=tags.nist_ai_rmf,
            status=status,
            target_fingerprint_at_discovery=target_fingerprint,
            content_markdown=content_markdown,
            content_html=content_html,
            written_at=written_at,
            run_id=run_id,
        )

    # ------------------------------------------------------------- helpers

    @staticmethod
    def _parse_llm_body(
        body: str,
    ) -> tuple[str, str, str, list[str], str]:
        """Split the LLM-returned markdown into the five fixed sections.

        Best-effort: any missing section is returned as an empty string /
        list. The body is expected to use level-2 headings exactly matching
        the prompt template.
        """
        sections = {
            "Clinical Impact": "",
            "Observed Behavior": "",
            "Expected Behavior": "",
            "Recommended Remediation": "",
            "Residual Risk": "",
        }
        current: str | None = None
        buf: list[str] = []
        for line in body.splitlines():
            stripped = line.strip()
            heading_match = re.match(r"^##\s+(.*?)\s*$", stripped)
            if heading_match and heading_match.group(1) in sections:
                if current is not None:
                    sections[current] = "\n".join(buf).strip()
                current = heading_match.group(1)
                buf = []
                continue
            if current is not None:
                buf.append(line)
        if current is not None:
            sections[current] = "\n".join(buf).strip()

        remediation_text = sections["Recommended Remediation"]
        remediation_bullets = [
            re.sub(r"^[-*]\s+", "", ln).strip()
            for ln in remediation_text.splitlines()
            if ln.strip().startswith(("-", "*"))
        ]
        if not remediation_bullets and remediation_text:
            remediation_bullets = [remediation_text]

        return (
            sections["Clinical Impact"],
            sections["Observed Behavior"],
            sections["Expected Behavior"],
            remediation_bullets,
            sections["Residual Risk"],
        )


def scrub_phi_obj_dict(obj: Any) -> Any:
    """Convenience: scrub a dict-like and return a JSON-safe dict (used in
    the HTTP block of the rendered report)."""
    from agentforge.observability.scrubber import scrub_phi_in_obj

    return scrub_phi_in_obj(obj)


__all__ = [
    "DocAnthropicClient",
    "DocumentationAgent",
    "VulnerabilityReport",
]
