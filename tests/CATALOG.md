# Test Catalog

Source of truth for the small Phase-0 unit suite. Freshness will be enforced by
a Phase-1 pre-commit hook (`tests/CATALOG.md` must match `pytest --collect-only`).

| Path | Marker | What it catches |
| --- | --- | --- |
| `tests/unit/judge/test_independence.py::test_judge_does_not_import_redteam` | `unit` | Judge module imports from `agentforge.redteam.*` (master plan §8.3 + AgDR-0001). |
| `tests/unit/target_adapter/test_allowlist.py` | `unit` | Out-of-scope hosts must raise `TargetNotAllowed`; in-allowlist hosts must pass (master plan §4 + AgDR-0002). |
