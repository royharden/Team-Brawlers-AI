# AgentForge — Adversarial AI Security Platform for the Clinical Co-Pilot

> **Sprint:** Gauntlet AI — Austin Admission, Week 3 (2026-05-12 → 2026-05-15)
> **Spec:** [Week3-AgentForge.md](../Week3-AgentForge.md)
> **Status:** Phase 0 in progress (see [planning/Plan_Whole_Claude_AgentForge_Adversarial_Platform_2026-05-13_status.md](planning/Plan_Whole_Claude_AgentForge_Adversarial_Platform_2026-05-13_status.md))

AgentForge is a four-agent platform that **continuously discovers, evaluates, escalates, regresses, and documents vulnerabilities** in an AI-assisted Clinical Co-Pilot deployed on top of OpenEMR. It is built for hospital CISOs, application-security engineers, and EHR product managers who need defensible evidence that an AI clinical workflow is — and remains — safe enough to put in front of physicians.

The platform attacks a **separate, deployed** Clinical Co-Pilot (the Wk1/Wk2 deliverable). The Co-Pilot source is read-only here — AgentForge lives in its own repository ([github.com/royharden/Team-Brawlers-AI](https://github.com/royharden/Team-Brawlers-AI)).

## The four agents (PRD-mandated)

| Agent | Role | Model | Trust |
|---|---|---|---|
| **Orchestrator** | Picks the next attack from coverage gaps + budget + recent target changes. Halts when cost accumulates without signal. | Claude Sonnet 4.6 | Strategic — only role allowed to schedule/halt/raise budget. |
| **Red Team** | Generates and mutates adversarial inputs. Only agent permitted to compose offensive payloads. Egress only via the allowlist-gated Target Adapter. | Claude Sonnet 4.6 with offensive-pentest framing — see [AgDR-0001](agentdocs/decisions/AgDR-0001-redteam-on-anthropic-not-fireworks.md). | Adversarial. |
| **Judge** (split) | **Internal Progress Judge** (Haiku 4.6 + deterministic detectors) feeds near-miss signal back to the Red Team. **External Final Judge** (Sonnet 4.6) emits the binding verdict — the only verdict that can become a finding. Validated against a 100-case meta-eval gold set. | Anthropic Haiku (internal) + Sonnet (external) | Binding — only the external judge produces findings. |
| **Documentation** | Writes professional vulnerability reports (`VR-####`) tagged with OWASP LLM Top 10 + OWASP Agentic Top 10 + AVID + NIST AI RMF, with reproducible attack sequences and regression-case emission. | Sonnet 4.6 (Haiku for drafts) | Reporting — autonomous up to severity ≥ HIGH, then notifier + human approval gate. |

**Regression Curator** and **Notifier** are services on Documentation/Observability — not separate agents. Every confirmed external-judge failure becomes a deterministic test case under `evals/regression/`, replayed on every target change.

## Repository layout

```
Team-Brawlers-AI/
├── README.md                 ← you are here
├── THREAT_MODEL.md           ← PRD hard gate — full attack surface map
├── ARCHITECTURE.md           ← PRD hard gate — multi-agent topology + Mermaid
├── USERS.md                  ← PRD hard gate — users + workflows + automation justification
├── COST_ANALYSIS.md          ← Phase 7 — actual + projected at 100 / 1K / 10K / 100K runs
├── agentforge/               ← Python package (see ARCHITECTURE.md §Agent contracts)
├── agentdocs/                ← Agent_LOG.md, agent_lessons.md, decisions/AgDR-NNNN-*.md
├── planning/                 ← Master plan (immutable) + status companion (mutable)
├── config/                   ← pricing.yml, target_allowlist.yml, notifier.yml
├── evals/                    ← seed catalog + regression cases + floor.json + meta-eval
├── reports/                  ← VR-####-<slug>.md / .html — vulnerability reports
├── scripts/                  ← smoke checks, gold-set builder, cost extrapolator
└── tests/                    ← unit / integration / e2e / eval / live_smoke
```

## Deployed URLs

- **Co-Pilot target:** _provisioning — see [AgDR-0002](agentdocs/decisions/AgDR-0002-defer-public-tunnel.md)_. Local-only during Phase 0–3; public Cloudflare quick-tunnel or ngrok before Tuesday MVP submission.
- **AgentForge platform UI:** _to be provisioned in Phase 7_.

## Setup (Phase 0 baseline — more added per phase)

### Prerequisites

- Python 3.11
- Poetry 1.8+
- Docker Desktop (for the local Co-Pilot target — `development-easy` stack)
- One Anthropic API key (used by all three Anthropic-backed roles unless `ANTHROPIC_API_KEY_REDTEAM` / `_JUDGE` are set separately)
- Langfuse cloud or self-hosted account
- (Optional) Fireworks.ai key — enables the planned Dolphin-72B Red Team variant. Off by default per AgDR-0001.

### Bootstrap

```bash
git clone https://github.com/royharden/Team-Brawlers-AI.git
cd Team-Brawlers-AI

# Install dependencies
poetry install

# Copy env template and fill in your credentials
cp .env.example .env
# Edit .env: ANTHROPIC_API_KEY, LANGFUSE_*, AGENT_MESSAGE_SIGNING_SECRET, TARGET_ALLOWLIST

# Sanity-check the local target Docker stack
./scripts/smoke_local_openemr.sh           # or smoke_local_openemr.ps1 on Windows

# Boot the platform API
poetry run uvicorn agentforge.api.main:app --reload --port 8100

# In a second terminal, run the Streamlit dashboard
poetry run streamlit run agentforge/ui/app.py
```

### Run a smoke attack

```bash
# Once Phase 2 ships:
poetry run tb smoke --target local
poetry run tb attack --category prompt_injection --strategy crescendo --count 5
poetry run tb regress --floor evals/floor.json
poetry run tb report --vr VR-0001
poetry run tb meta-eval --layer external_final
```

All commands respect the budget guard (`BUDGET_*` env vars) and the `TARGET_ALLOWLIST`. The Red Team agent never touches any host not in the allowlist.

## How vulnerabilities flow

1. **Orchestrator** reads the coverage matrix (8 categories × 9 strategies), open high-severity findings, recent target fingerprint changes, and remaining budget; picks the next batch of `(category, strategy)` pairs.
2. **Red Team** samples a seed from `agentforge/redteam/seed_catalog/<category>.yaml`, composes a mutator chain (encoders → role-wrap → persuasion → crescendo/TAP/linear/BLJ), and renders the rendered prompt + optional adversarial document.
3. **Target Adapter** routes through one of four modes (`sidecar_direct` / `openemr_gateway` / `browser_openemr` / `fhir_smart`), gated by the allowlist. Synthetic patients only.
4. **Internal Progress Judge** (deterministic detectors first, Haiku for ambiguous cases) gives near-miss signal back to the Red Team for the next mutation step. **Never produces a finding.**
5. **External Final Judge** (Sonnet 4.6, independent of Red Team) runs the full rubric set for the category and issues the binding verdict.
6. **Documentation Agent** consumes external-judge failures, dedupes via `VulnerabilityClass`, writes a `VR-####` report tagged with OWASP LLM Top 10 + Agentic Top 10 + AVID + NIST AI RMF, emits a regression case under `evals/regression/VR-####.json` (refuses if `what_bug_this_catches` is empty).
7. **Notifier** fires for severity ≥ HIGH; human approval required for: budget raises, false-positive close, floor.json change, target-fix push, external notify.

## Observability

- **Langfuse Cloud** — every LLM call traced, cost-tagged, PHI-scrubbed.
- **SQLite WORM flight recorder** (`flight_events`) — append-only event log; replayable for incident review.
- **Streamlit dashboard** — Dashboard, Coverage matrix, VulnReports, Cost, LiveRun, JudgeMeta, AttackLineage, DefenseDelta.
- **Defense Delta Score** — fingerprint-snapshotted aggregate of pass-rates across the coverage matrix; the trend a hospital CISO actually watches.

## Safety contract

- **`TARGET_ALLOWLIST` is enforced on every outbound call.** Out-of-scope hosts raise `TargetNotAllowed` before any payload is sent.
- **Synthetic patients only.** `scripts/seed_target_patients.py` creates obviously-test fixtures (Alice Test, Bob Test, Carol Test).
- **HMAC-signed inter-agent messages.** Every `agent_messages` row carries a signature verified at ingest.
- **Human approval gates** on: adding a new target host, raising the budget above `BUDGET_EXPLORATORY_USD`, closing a finding as false positive, modifying `evals/floor.json`, pushing a target fix, and any external notifier.
- **Judge independence lint** (`tests/unit/judge/test_independence.py`) blocks any judge module from importing `agentforge.redteam.*`.

## Project documents

- [THREAT_MODEL.md](THREAT_MODEL.md) — full attack-surface map (9 categories including `clinical_integrity`, `observability_leakage`, `platform_self_attack`).
- [ARCHITECTURE.md](ARCHITECTURE.md) — multi-agent topology + Mermaid diagram + agent contracts + approval gates + tradeoffs.
- [USERS.md](USERS.md) — personas, workflows, automation justification.
- [planning/](planning/) — master plan (immutable) + status companion (mutable; reality lives here).
- [agentdocs/](agentdocs/) — chronological Agent_LOG, agent_lessons, and AgDR decision records.

## License

MIT — see [LICENSE](LICENSE).

## Authors

Roy Harden ([@royharden](https://github.com/royharden)) + autonomous agents (Claude Opus 4.7, Sonnet 4.6, Haiku 4.6) operating per the documentation framework in `.claude/skills/documentation-framework-v1/`.
