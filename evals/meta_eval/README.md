# Judge Meta-Eval

This directory holds the hand-labeled gold set used to validate the External
Final Judge (and, later, the Internal Progress Judge). Per master plan §22 DoD 16
and the PRD ("how you validate the judge itself"), the gold set is the
independent ground truth the platform measures the judge against.

## Layout

- `gold_set/v1.jsonl` — versioned gold set. Line 1 is the header
  (`version`, `created_at`, `n_cases`, `label_provenance`, `cases_follow:true`),
  followed by one `GoldCase` JSON object per line.
- `judge_<layer>_<version>_metrics.json` — output of the runner (gitignored
  output; reproducible from the gold set + judge code).

## Adding cases

Edit `gold_set/v1.jsonl` (or bump to a `v2.jsonl`). Each line MUST validate
against `agentforge.judge.meta_eval.gold_set_schema.GoldCase`:

- `label_rationale` is mandatory and must be ≥ 10 characters — the human
  labeler's reasoning for choosing `expected_label`.
- Use synthetic patients only (Alice Test / Bob Test / Carol Test). No real PHI.
- `expected_failed_rubrics` lists the rubric ids the case asserts MUST fail
  (empty when `expected_label == "passed"`).
- Bump the header's `n_cases` to match the on-disk count.

## Running

The runner is invoked module-level:

```python
from agentforge.judge.meta_eval import run_meta_eval
metrics = run_meta_eval(Path("evals/meta_eval/gold_set/v1.jsonl"))
```

Once the CLI lands: `tb meta-eval --layer external_final` will load this gold
set, run the External Final Judge against every case, and write
`judge_external_final_v1_metrics.json` next to this README.

## Floor

The current judge floor is defined in `evals/floor.json::judge_floor.external_final`
(`precision >= 0.85`, `recall >= 0.80`, `f1 >= 0.82`). Raising the floor
requires an AgDR decision record (per the testing-discipline contract) — do
not lower it silently.
