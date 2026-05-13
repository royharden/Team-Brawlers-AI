# evals/

Layout:

- `cases/<category>/*.yaml` — seed attack cases (master plan §9, Phase 2/5).
- `regression/VR-####.json` — confirmed-exploit replays. One file per exploit.
- `results/*.jsonl` — per-run outputs (one JSONL per orchestrated run).
- `floor.json` — CI gate: per-category pass-rate floors + judge meta-eval floor + regression floor.
- `case_schema.json` — JSON Schema (Draft 2020-12) for seed cases. `what_bug_this_catches` is REQUIRED.
- `meta_eval/` — judge meta-eval gold-set metrics.

Eval gate workflow (CI):

1. `python -m agentforge.cli regress --floor evals/floor.json` runs all regression cases.
2. Floor is violated if any previously-passing case flips to fail
   (`max_new_regressions_per_run = 0`) or if `external_final` judge metrics fall below
   the `judge_floor` thresholds.
3. Failure is non-zero exit; PRs cannot merge.
