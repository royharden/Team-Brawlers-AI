"""Schema validation guard for the seed catalog.

Every YAML under `evals/cases/**/*.yaml` MUST validate against
`evals/case_schema.json`. Every entry inside each
`agentforge/redteam/seed_catalog/<category>.yaml` `seeds:` array MUST validate too.

This test is the gatekeeper that keeps the schema and the catalog from drifting.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator

# tests/unit/judge/ → 3 parents to reach the inner repo root.
REPO_ROOT: Path = Path(__file__).resolve().parents[3]
SCHEMA_PATH: Path = REPO_ROOT / "evals" / "case_schema.json"
CASES_ROOT: Path = REPO_ROOT / "evals" / "cases"
CATALOG_ROOT: Path = REPO_ROOT / "agentforge" / "redteam" / "seed_catalog"


def _load_schema() -> dict[str, Any]:
    with SCHEMA_PATH.open(encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.unit
def test_case_schema_is_well_formed() -> None:
    """The schema itself must be a valid Draft 2020-12 schema."""
    schema = _load_schema()
    Draft202012Validator.check_schema(schema)


@pytest.mark.unit
def test_every_individual_seed_file_validates() -> None:
    """Each YAML under evals/cases/<category>/ must validate as a single seed case."""
    schema = _load_schema()
    validator = Draft202012Validator(schema)

    yaml_paths = sorted(CASES_ROOT.glob("**/*.yaml"))
    assert yaml_paths, f"No seed YAMLs under {CASES_ROOT}"

    failures: list[str] = []
    for path in yaml_paths:
        with path.open(encoding="utf-8") as f:
            doc = yaml.safe_load(f)
        errs = list(validator.iter_errors(doc))
        if errs:
            details = "; ".join(f"{list(e.absolute_path) or '<root>'}: {e.message}" for e in errs)
            failures.append(f"{path.relative_to(REPO_ROOT)}: {details}")

    assert not failures, "Seed schema violations:\n" + "\n".join(failures)


@pytest.mark.unit
def test_every_catalog_entry_validates() -> None:
    """Each entry inside `seeds:` in every catalog YAML must validate."""
    schema = _load_schema()
    validator = Draft202012Validator(schema)

    catalog_paths = sorted(CATALOG_ROOT.glob("*.yaml"))
    assert catalog_paths, f"No catalog YAMLs under {CATALOG_ROOT}"

    failures: list[str] = []
    for path in catalog_paths:
        with path.open(encoding="utf-8") as f:
            doc = yaml.safe_load(f)
        assert isinstance(doc, dict), f"{path}: catalog is not a mapping"
        seeds = doc.get("seeds")
        assert isinstance(seeds, list) and seeds, f"{path}: missing/empty seeds list"
        for index, seed in enumerate(seeds):
            errs = list(validator.iter_errors(seed))
            if errs:
                details = "; ".join(
                    f"{list(e.absolute_path) or '<root>'}: {e.message}" for e in errs
                )
                seed_id = (
                    seed.get("id", f"<index {index}>")
                    if isinstance(seed, dict)
                    else f"<index {index}>"
                )
                failures.append(f"{path.relative_to(REPO_ROOT)}[{seed_id}]: {details}")

    assert not failures, "Catalog schema violations:\n" + "\n".join(failures)


@pytest.mark.unit
def test_individual_seeds_and_catalog_entries_match() -> None:
    """The individual per-seed YAMLs and the catalog entries must carry the same set
    of seed `id`s for each category. Drift here means a seed exists in one shape
    but not the other and the RedTeamAgent + the eval harness will disagree."""
    cases_by_category: dict[str, set[str]] = {}
    for path in CASES_ROOT.glob("**/*.yaml"):
        category = path.parent.name
        with path.open(encoding="utf-8") as f:
            doc = yaml.safe_load(f)
        cases_by_category.setdefault(category, set()).add(doc["id"])

    catalog_by_category: dict[str, set[str]] = {}
    for path in CATALOG_ROOT.glob("*.yaml"):
        category = path.stem
        with path.open(encoding="utf-8") as f:
            doc = yaml.safe_load(f)
        catalog_by_category[category] = {seed["id"] for seed in doc.get("seeds", [])}

    mismatches: list[str] = []
    for category in sorted(set(cases_by_category) | set(catalog_by_category)):
        case_ids = cases_by_category.get(category, set())
        catalog_ids = catalog_by_category.get(category, set())
        only_in_cases = case_ids - catalog_ids
        only_in_catalog = catalog_ids - case_ids
        if only_in_cases or only_in_catalog:
            mismatches.append(
                f"{category}: only_in_cases={sorted(only_in_cases)} "
                f"only_in_catalog={sorted(only_in_catalog)}"
            )
    assert not mismatches, "Seed-case / catalog drift:\n" + "\n".join(mismatches)
