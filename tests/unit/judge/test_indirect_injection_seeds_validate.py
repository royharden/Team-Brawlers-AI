"""Validation tests for the indirect-injection seed family — master plan
§14 Phase 5 task 1+2.

These tests pin the schema shape of the ``indirect_injection`` extension
block and re-run the schema drift detector against the broader catalog
so additions here can't silently break the existing harness contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator

pytestmark = pytest.mark.unit

# tests/unit/judge/ → 3 parents to reach the inner repo root.
REPO_ROOT: Path = Path(__file__).resolve().parents[3]
SCHEMA_PATH: Path = REPO_ROOT / "evals" / "case_schema.json"
CASES_ROOT: Path = REPO_ROOT / "evals" / "cases"
CATALOG_ROOT: Path = REPO_ROOT / "agentforge" / "redteam" / "seed_catalog"


_NEW_PI_FILES: tuple[str, ...] = (
    "prompt_injection_indirect_lab_pdf_persona_override.yaml",
    "prompt_injection_indirect_lab_pdf_disclose_other_patient.yaml",
    "prompt_injection_indirect_intake_form_system_prompt_extract.yaml",
)

_NEW_CI_FILES: tuple[str, ...] = (
    "clinical_integrity_lab_pdf_fake_glucose_with_unit_swap.yaml",
    "clinical_integrity_lab_pdf_wrong_patient_dob.yaml",
    "clinical_integrity_lab_pdf_off_page_correction.yaml",
)


def _load_schema() -> dict[str, Any]:
    with SCHEMA_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.mark.parametrize("filename", _NEW_PI_FILES)
def test_each_new_pi_seed_validates_against_schema(filename: str) -> None:
    schema = _load_schema()
    validator = Draft202012Validator(schema)
    path = CASES_ROOT / "prompt_injection" / filename
    assert path.exists(), f"missing seed file: {path}"
    doc = _load_yaml(path)
    errors = list(validator.iter_errors(doc))
    assert not errors, "\n".join(f"{list(e.absolute_path)}: {e.message}" for e in errors)


@pytest.mark.parametrize("filename", _NEW_CI_FILES)
def test_each_new_ci_seed_validates_against_schema(filename: str) -> None:
    schema = _load_schema()
    validator = Draft202012Validator(schema)
    path = CASES_ROOT / "clinical_integrity" / filename
    assert path.exists(), f"missing seed file: {path}"
    doc = _load_yaml(path)
    errors = list(validator.iter_errors(doc))
    assert not errors, "\n".join(f"{list(e.absolute_path)}: {e.message}" for e in errors)


def test_indirect_injection_block_required_fields() -> None:
    """The schema's `additionalProperties` allows the extension block,
    but the mutator + PDF factory require these three fields. Pin them
    here so a seed author can't omit them silently.
    """
    required = {"document_kind", "injection_placement", "injected_text"}
    failures: list[str] = []
    for category, filenames in (
        ("prompt_injection", _NEW_PI_FILES),
        ("clinical_integrity", _NEW_CI_FILES),
    ):
        for filename in filenames:
            path = CASES_ROOT / category / filename
            doc = _load_yaml(path)
            block = doc.get("indirect_injection")
            if not isinstance(block, dict):
                failures.append(f"{filename}: missing indirect_injection block")
                continue
            missing = required - set(block.keys())
            if missing:
                failures.append(f"{filename}: missing fields {sorted(missing)}")
            placement = block.get("injection_placement")
            assert placement in {
                "after_results",
                "header_footer",
                "metadata",
                "off_page",
            }, f"{filename}: unknown placement {placement!r}"
            kind = block.get("document_kind")
            assert kind in {"lab", "intake_form"}, (
                f"{filename}: unknown document_kind {kind!r}"
            )
    assert not failures, "\n".join(failures)


def test_seed_catalog_drift_still_aligns() -> None:
    """Re-run the same drift check the main schema test uses, scoped here
    so a regression in the indirect-injection catalog entries fails
    locally with a clear signal."""
    cases_by_category: dict[str, set[str]] = {}
    for path in CASES_ROOT.glob("**/*.yaml"):
        category = path.parent.name
        doc = _load_yaml(path)
        cases_by_category.setdefault(category, set()).add(doc["id"])

    catalog_by_category: dict[str, set[str]] = {}
    for path in CATALOG_ROOT.glob("*.yaml"):
        category = path.stem
        doc = _load_yaml(path)
        catalog_by_category[category] = {seed["id"] for seed in doc.get("seeds", [])}

    for category in ("prompt_injection", "clinical_integrity"):
        case_ids = cases_by_category.get(category, set())
        catalog_ids = catalog_by_category.get(category, set())
        assert case_ids == catalog_ids, (
            f"{category} drift: "
            f"only_in_cases={sorted(case_ids - catalog_ids)} "
            f"only_in_catalog={sorted(catalog_ids - case_ids)}"
        )
