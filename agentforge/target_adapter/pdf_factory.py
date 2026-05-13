"""PDF factory for indirect-injection attacks — master plan §14 Phase 5 task 1.

Renders adversarial PDFs in-memory (BytesIO) and returns raw bytes ready to be
uploaded through the OpenEMR document gateway or the sidecar's lab-PDF intake
endpoint. The factory is the source of bytes that lands on
`MutatedAttack.rendered_document`.

Every PDF emitted by this factory round-trips through pypdf: the injected text
MUST extract back as readable text. Otherwise the indirect-injection seed
silently fails to land its payload on the target's LLM context. The
post-render assertion in each public method is the regression guardrail
described in the master plan.

All patients referenced by callers are **synthetic** (Alice Test / Bob Test /
Carol Test). The PDF /Producer metadata is set to "AgentForge PDFFactory v1"
so generated artifacts are traceable in audit logs.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any, Literal

from pydantic import BaseModel
from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

__all__ = ["LabRow", "PDFFactory"]

InjectionPlacement = Literal["after_results", "header_footer", "metadata", "off_page"]

_PRODUCER_NAME: str = "AgentForge PDFFactory v1"


class LabRow(BaseModel):
    """A single row of a lab-result table."""

    name: str
    value: str
    unit: str
    reference_range: str = ""
    flag: str = ""


class PDFFactory:
    """Renders adversarial PDFs for indirect-injection attacks.

    Master plan §14 Phase 5 task 1. Builds the PDF in-memory (BytesIO),
    returns bytes ready to upload through the OpenEMR document gateway
    or the sidecar's lab-PDF intake endpoint.

    Round-trips through pypdf: every PDF this factory emits MUST extract
    back to text that contains the injected payload. Otherwise the
    indirect-injection seed will silently fail to land its bytes on the
    target's LLM context.
    """

    def __init__(self, *, default_author: str = "AgentForge Synthetic Generator") -> None:
        self._default_author = default_author

    # ------------------------------------------------------------------
    # Public renderers
    # ------------------------------------------------------------------

    def lab_with_injection(
        self,
        *,
        patient_name: str,
        patient_dob: str,
        lab_panel: list[LabRow],
        injected_text: str,
        injection_placement: InjectionPlacement = "after_results",
    ) -> bytes:
        """Render a clinical-lab PDF with `injected_text` smuggled in.

        Placements:
          - after_results: visible-but-near-the-bottom block (catches most
            naive PDF text extractors).
          - header_footer: in the running header/footer; many extractors
            keep these in the body stream.
          - metadata: PDF /Title or /Subject metadata; pdfplumber surfaces
            this in many configs.
          - off_page: text positioned at negative y-coordinates (invisible
            to humans, visible to most extractors).
        """
        title = f"Clinical Lab Report - {patient_name}"
        subject = "Routine chemistry panel"
        body = self._render_lab_body(
            patient_name=patient_name,
            patient_dob=patient_dob,
            lab_panel=lab_panel,
            injected_text=injected_text,
            injection_placement=injection_placement,
        )
        pdf_bytes = self._stamp_metadata(
            body,
            title=title,
            subject=subject,
            injected_text=injected_text,
            injection_placement=injection_placement,
        )
        self._assert_extracts(pdf_bytes, injected_text)
        return pdf_bytes

    def intake_form_with_injection(
        self,
        *,
        patient_name: str,
        patient_dob: str,
        intake_fields: dict[str, str],
        injected_text: str,
        injection_placement: InjectionPlacement = "header_footer",
    ) -> bytes:
        """Render an intake form with smuggled instructions."""
        title = f"Patient Intake Form - {patient_name}"
        subject = "Outpatient intake"
        body = self._render_intake_body(
            patient_name=patient_name,
            patient_dob=patient_dob,
            intake_fields=intake_fields,
            injected_text=injected_text,
            injection_placement=injection_placement,
        )
        pdf_bytes = self._stamp_metadata(
            body,
            title=title,
            subject=subject,
            injected_text=injected_text,
            injection_placement=injection_placement,
        )
        self._assert_extracts(pdf_bytes, injected_text)
        return pdf_bytes

    @staticmethod
    def round_trip_extract(pdf_bytes: bytes) -> str:
        """Run pypdf over the bytes and return concatenated text from every
        page plus any /Title and /Subject metadata fields. Used by the
        post-render assertion and by the round-trip tests.
        """
        reader = PdfReader(BytesIO(pdf_bytes))
        parts: list[str] = []
        for page in reader.pages:
            text = page.extract_text() or ""
            parts.append(text)
        meta: Any = reader.metadata or {}
        # Metadata keys are PDF /Name objects; access by indexing string keys.
        for key in ("/Title", "/Subject", "/Keywords", "/Author"):
            try:
                value = meta.get(key)  # type: ignore[attr-defined]
            except Exception:
                value = None
            if value:
                parts.append(str(value))
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Body renderers (pre-metadata)
    # ------------------------------------------------------------------

    def _render_lab_body(
        self,
        *,
        patient_name: str,
        patient_dob: str,
        lab_panel: list[LabRow],
        injected_text: str,
        injection_placement: InjectionPlacement,
    ) -> bytes:
        """Render the visible body of a lab PDF (everything but metadata
        stamping). Returns the raw bytes from reportlab.
        """
        buf = BytesIO()
        doc = SimpleDocTemplate(
            buf,
            pagesize=letter,
            title=f"Clinical Lab Report - {patient_name}",
            author=self._default_author,
            subject="Routine chemistry panel",
            producer=_PRODUCER_NAME,
            leftMargin=0.75 * inch,
            rightMargin=0.75 * inch,
            topMargin=1.0 * inch,
            bottomMargin=1.0 * inch,
        )
        styles = getSampleStyleSheet()
        story: list = []

        header_injection = injected_text if injection_placement == "header_footer" else ""

        story.append(Paragraph("Synthetic Test Lab - Report", styles["Title"]))
        story.append(Spacer(1, 0.15 * inch))
        story.append(
            Paragraph(
                f"<b>Patient:</b> {patient_name} &nbsp;&nbsp;" f"<b>DOB:</b> {patient_dob}",
                styles["Normal"],
            )
        )
        story.append(Spacer(1, 0.2 * inch))

        # Lab results table
        table_data: list[list[str]] = [["Analyte", "Value", "Unit", "Reference Range", "Flag"]]
        for row in lab_panel:
            table_data.append([row.name, row.value, row.unit, row.reference_range, row.flag])
        table = Table(
            table_data,
            colWidths=[1.6 * inch, 1.0 * inch, 1.0 * inch, 1.6 * inch, 0.6 * inch],
        )
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                    ("ALIGN", (1, 1), (3, -1), "RIGHT"),
                ]
            )
        )
        story.append(table)
        story.append(Spacer(1, 0.25 * inch))

        if injection_placement == "after_results":
            story.append(
                Paragraph(
                    "<i>Lab interpretation notes:</i>",
                    styles["Italic"],
                )
            )
            story.append(Paragraph(self._escape_paragraph(injected_text), styles["Normal"]))

        story.append(Spacer(1, 0.25 * inch))
        story.append(
            Paragraph(
                "<font size=8>Synthetic test data only - no real PHI. "
                "Generated by AgentForge PDFFactory v1.</font>",
                styles["Normal"],
            )
        )

        on_page = self._make_on_page(
            header_injection=header_injection,
            off_page_injection=(injected_text if injection_placement == "off_page" else ""),
        )
        doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
        return buf.getvalue()

    def _render_intake_body(
        self,
        *,
        patient_name: str,
        patient_dob: str,
        intake_fields: dict[str, str],
        injected_text: str,
        injection_placement: InjectionPlacement,
    ) -> bytes:
        buf = BytesIO()
        doc = SimpleDocTemplate(
            buf,
            pagesize=letter,
            title=f"Patient Intake Form - {patient_name}",
            author=self._default_author,
            subject="Outpatient intake",
            producer=_PRODUCER_NAME,
            leftMargin=0.75 * inch,
            rightMargin=0.75 * inch,
            topMargin=1.0 * inch,
            bottomMargin=1.0 * inch,
        )
        styles = getSampleStyleSheet()
        story: list = []

        header_injection = injected_text if injection_placement == "header_footer" else ""

        story.append(Paragraph("Patient Intake Form", styles["Title"]))
        story.append(Spacer(1, 0.15 * inch))
        story.append(
            Paragraph(
                f"<b>Patient:</b> {patient_name} &nbsp;&nbsp;" f"<b>DOB:</b> {patient_dob}",
                styles["Normal"],
            )
        )
        story.append(Spacer(1, 0.2 * inch))

        for label, value in intake_fields.items():
            story.append(
                Paragraph(
                    f"<b>{self._escape_paragraph(label)}:</b> " f"{self._escape_paragraph(value)}",
                    styles["Normal"],
                )
            )
            story.append(Spacer(1, 0.1 * inch))

        if injection_placement == "after_results":
            story.append(Spacer(1, 0.2 * inch))
            story.append(
                Paragraph(
                    "<i>Additional notes:</i>",
                    styles["Italic"],
                )
            )
            story.append(Paragraph(self._escape_paragraph(injected_text), styles["Normal"]))

        story.append(Spacer(1, 0.25 * inch))
        story.append(
            Paragraph(
                "<font size=8>Synthetic test intake form - no real PHI. "
                "Generated by AgentForge PDFFactory v1.</font>",
                styles["Normal"],
            )
        )

        on_page = self._make_on_page(
            header_injection=header_injection,
            off_page_injection=(injected_text if injection_placement == "off_page" else ""),
        )
        doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
        return buf.getvalue()

    # ------------------------------------------------------------------
    # Canvas-level header/footer + off-page placement
    # ------------------------------------------------------------------

    @staticmethod
    def _make_on_page(*, header_injection: str, off_page_injection: str):
        """Build the onPage callback used by SimpleDocTemplate. The callback
        draws header/footer text and any off-page payload at canvas-level so
        pypdf still extracts the strings from the content stream.
        """

        def _on_page(c: rl_canvas.Canvas, _doc) -> None:
            page_width, page_height = letter
            if header_injection:
                # Running header (top of every page)
                c.saveState()
                c.setFont("Helvetica-Oblique", 8)
                # Draw a sanitized one-line version near the top margin
                header_line = header_injection.replace("\n", " ").strip()
                c.drawString(0.5 * inch, page_height - 0.5 * inch, header_line)
                # Also drop in the footer so headers AND footers carry the payload
                c.drawString(0.5 * inch, 0.5 * inch, header_line)
                c.restoreState()
            if off_page_injection:
                # Off-page placement: negative y (below visible page area).
                # ReportLab clips at draw time but the underlying content
                # stream still carries the text op-codes, which pypdf
                # extracts.
                c.saveState()
                c.setFont("Helvetica", 6)
                off_line = off_page_injection.replace("\n", " ").strip()
                # Position well below 0 so a human reader never sees it,
                # and at a tiny x so layout never overlaps the visible body.
                c.drawString(0.1 * inch, -50.0, off_line)
                c.restoreState()

        return _on_page

    # ------------------------------------------------------------------
    # Metadata stamping via pypdf
    # ------------------------------------------------------------------

    @staticmethod
    def _stamp_metadata(
        pdf_bytes: bytes,
        *,
        title: str,
        subject: str,
        injected_text: str,
        injection_placement: InjectionPlacement,
    ) -> bytes:
        """Re-write the metadata dictionary so /Producer is always
        "AgentForge PDFFactory v1" and (when injection_placement=='metadata')
        the injected payload is dropped into /Subject. We round-trip
        through pypdf so metadata is canonical and pypdf's own extractor
        can surface it.
        """
        reader = PdfReader(BytesIO(pdf_bytes))
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        # pypdf treats /Producer etc. as PdfObject internally, but accepts strings on
        # add_metadata via runtime coercion. Type-narrow to Any so the dict accepts strs.
        existing: dict[Any, Any] = dict(reader.metadata or {})
        existing["/Producer"] = _PRODUCER_NAME
        existing.setdefault("/Title", title)
        if injection_placement == "metadata":
            existing["/Subject"] = injected_text
            existing["/Keywords"] = injected_text
        else:
            existing.setdefault("/Subject", subject)
        writer.add_metadata(existing)
        out = BytesIO()
        writer.write(out)
        return out.getvalue()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _escape_paragraph(text: str) -> str:
        """Minimal escaping for reportlab Paragraph mini-language. The
        injected_text is adversarial — we keep the visible content but
        neutralize any `<` / `>` that would otherwise crash the parser.
        """
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    @classmethod
    def _assert_extracts(cls, pdf_bytes: bytes, injected_text: str) -> None:
        extracted = cls.round_trip_extract(pdf_bytes)
        # Match on the meaningful prefix so soft line-wraps don't break the
        # assertion. We require at least 20 chars (or the whole payload if
        # shorter) to survive the round-trip.
        probe = injected_text.strip()
        if not probe:
            return
        # Strip whitespace from both sides so wrapped text still matches.
        norm_extracted = " ".join(extracted.split())
        norm_probe = " ".join(probe.split())
        # If the full payload is in the extracted text, we're good.
        if norm_probe in norm_extracted:
            return
        # Otherwise check the first 30 chars survived — a robust enough
        # smoke test that the injection landed somewhere in the stream.
        head = norm_probe[: min(30, len(norm_probe))]
        if head in norm_extracted:
            return
        raise RuntimeError(
            "PDFFactory: injected_text did not round-trip through pypdf. "
            f"probe head={head!r} not in extracted text (len={len(extracted)})."
        )
