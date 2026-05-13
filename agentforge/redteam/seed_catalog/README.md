# Red Team Seed Catalog

One YAML file per attack category lands here in Phase 2 / Phase 5. Files:

- `prompt_injection.yaml`
- `data_exfiltration.yaml`
- `state_corruption.yaml`
- `tool_misuse.yaml`
- `denial_of_service.yaml`
- `identity_role.yaml`
- `clinical_integrity.yaml`
- `observability_leakage.yaml`
- `platform_self_attack.yaml`

Schema is defined in `evals/case_schema.json`. Each case **must** include a
non-empty `what_bug_this_catches` string.
