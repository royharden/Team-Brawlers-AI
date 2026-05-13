# AgentForge — 3-5 Minute Demo Script

**Audience:** Hospital CISO / Clinical AI Security Engineer / EHR PM.
**Goal:** Show the multi-agent platform finding, scoring, documenting, and gating a regression for a Clinical Co-Pilot exploit — autonomously.
**Recording target:** YouTube unlisted; link from `README.md`.

---

## Setup before recording (do this first; not on camera)

1. `git pull origin main` → confirm at the latest commit.
2. `poetry install`.
3. `cp .env.example .env`; populate `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`, `LANGFUSE_PUBLIC_KEY/SECRET_KEY/HOST`, `AGENT_MESSAGE_SIGNING_SECRET=$(python -c "import secrets;print(secrets.token_hex(32))")`.
4. `python scripts/generate_sample_vrs.py` → produces `reports/VR-0001.md`, `VR-0002.md`, `VR-0003.md` + matching regression cases under `evals/regression/`. (If the operator has the local OpenEMR Docker stack up, skip this step and run a live attack instead.)
5. In two terminals:
   - **API:** `poetry run uvicorn agentforge.api.main:app --reload --port 8100`
   - **UI:** `poetry run streamlit run agentforge/ui/app.py`
6. Open the Streamlit URL in a clean browser window.

---

## Demo flow (4 minutes 30 seconds, with 30s buffer)

### 0:00 – 0:30 — Cold open

> "AgentForge is a four-agent adversarial AI security platform that continuously hunts vulnerabilities in AI-assisted clinical workflows. I built it in five days against a Clinical Co-Pilot deployed on OpenEMR. Today I'll show you how the platform turns one autonomous attack run into a defensible vulnerability report a hospital CISO can act on."

Show the Streamlit Dashboard page. Point at:
- **Provider banner**: "Red Team on OpenRouter Dolphin-Mistral 24B Venice (uncensored). Judges on Anthropic Sonnet + Haiku. Cross-vendor by design — judge independence is non-negotiable."
- **Target fingerprint**: "Every time the target's `/healthz` hash, Docker image tag, or git rev changes, the platform auto-triggers a regression replay against every confirmed exploit."
- **Judge floor met**: precision/recall/F1 badges all green.

### 0:30 – 1:30 — The four agents

Switch to `ARCHITECTURE.md` (markdown preview) and the Mermaid diagram.

> "The PRD requires four distinct agents with distinct trust levels. **Orchestrator** picks the next attack from coverage gaps and budget. **Red Team** mutates payloads — it's the only agent permitted to compose offensive content, and it runs on an uncensored model so it doesn't refuse legitimate pentest framing. **Judge** is split: an Internal Progress Judge gives the Red Team near-miss feedback; an External Final Judge issues the binding verdict that's *the only* signal that can become a finding. **Documentation** writes the report. Regression Curator and Notifier are services on Documentation — same trust level."

Click through the Mermaid box for each agent. Land on the **Cross-vendor judge independence** callout in the Departures section — explicitly call out AgDR-0013.

### 1:30 – 2:30 — Live attack flow

Switch to the **Coverage** page → show the 8×9 matrix with seeded cells.

Switch to the **VulnReports** page → show VR-0001 / VR-0002 / VR-0003 in the list.

Click VR-0001 (the data-exfiltration / SSN disclosure one). On camera:

> "Here's what the Documentation Agent produces from one confirmed exploit. The OWASP LLM Top 10, OWASP Agentic Top 10, AVID, and NIST AI RMF tags are all auto-applied by the Tagger. DEFCON and safety score are derived from the rubric outcomes. The attack prompt and the target's response are quoted as **evidence** — the platform never executes embedded instructions inside the response, which is its own threat model category (`platform_self_attack`)."

Scroll to the **Minimal Reproducer** block. Highlight:
- PHI fully scrubbed (`[REDACTED-SSN]`, `[REDACTED-DOB]`, `[REDACTED-PHONE]`).
- The `tb regress --case VR-0001` replay command.

### 2:30 – 3:15 — Regression in action

Drop to a terminal:

```bash
poetry run tb regress --mock tests/fixtures/regression_replay/ --floor evals/floor.json
```

Show the JSONL output. Point at:
- The `target_fingerprint` recorded on each replay.
- The `unexpected_passes` list (empty here — exploits still reproduce, which is correct until we ship the OpenEMR fix).
- Exit code 0 (no NEW regressions; the floor is met).

> "Every confirmed exploit ships with a deterministic regression case under `evals/regression/`. The runner replays them on every target change. When a previously-failing case starts passing, that's a fix candidate — when it flips back to failing, that's a new regression. The CI floor (`evals/floor.json`) gates merges."

### 3:15 – 3:55 — Judge meta-eval

Switch to the **JudgeMeta** Streamlit page.

> "The PRD calls out judge validation as a hard problem. We hand-labeled a 30-case gold set — 10 of those are adversarial against the judge itself, where the target response contains directives aimed at flipping the verdict. Here's the latest run."

Point at: precision = recall = F1 = Krippendorff α = 1.0. Floor met for every metric. Click through to `evals/meta_eval/judge_external_final_v1_metrics.json` to show the raw artifact.

### 3:55 – 4:30 — Cost model

Switch to the **Cost** Streamlit page.

> "The PRD asks for projected cost at 100, 1K, 10K, and 100K runs — and warns that it's not just cost-per-token times N. Here's why."

Show the four-row projection. Hover the 100K row.

> "Per-run cost actually *falls* at 100K because the External Judge starts batching five rubrics into one Sonnet call — 30% cost reduction in that role. Naive 10x extrapolation would predict $4,392 at 100K. Modelled, with the architectural changes, it's $3,298. That's the kind of decision a CISO needs to see in writing before approving continuous security testing."

Open `COST_ANALYSIS.md` in a tab. Scroll to the **Cost guardrails** section.

> "Plus the Budget Guard halts when cost accumulates without producing signal — 25 null runs and three dollars without a finding, the run stops. No runaway bills."

### 4:30 – 5:00 — Close

> "Multi-agent. Judge-independent. Synthetic patients only — no real PHI ever touches the platform. Regression-gated. Cost-bounded. OWASP/AVID/NIST-tagged reports. 393 unit tests passing. Repo and deployed URL in the description. Thanks for watching."

End.

---

## 90-second backup cut (if the full demo runs long)

- 0:00–0:20: cold open (same wording).
- 0:20–0:50: ARCHITECTURE.md Mermaid + the four-agent line.
- 0:50–1:20: open VR-0001 in the UI; point at scrubbed PHI + the replay command.
- 1:20–1:30: cut to the Cost page; one sentence about the 100K leverage point. End.

---

## What to NOT show on camera

- The `.env` file. Don't share screen with secrets in any open tab.
- Live API keys in any terminal scrollback.
- The `data/agentforge.sqlite` and `data/notifier_queue.jsonl` files (synthetic data; reveals internal IDs).
- The `agentdocs/` and `planning/` directories — they're gitignored for a reason; not for public consumption.

## Submission requirements check before recording

- [ ] `THREAT_MODEL.md` exists and renders cleanly in GitHub.
- [ ] `ARCHITECTURE.md` Mermaid renders in GitHub.
- [ ] `USERS.md` covers the four personas.
- [ ] `COST_ANALYSIS.md` four-scale table renders.
- [ ] `reports/VR-0001.md`, `VR-0002.md`, `VR-0003.md` all on disk.
- [ ] `evals/regression/VR-0001.json`, `VR-0002.json`, `VR-0003.json` all on disk.
- [ ] `evals/meta_eval/judge_external_final_v1_metrics.json` shows floor met.
- [ ] `tb regress --mock` exits 0 locally.
- [ ] `pytest tests/ -q` exits 0 locally.
- [ ] Both deployed URLs reachable from outside the local machine (target via tunnel; platform UI publicly reachable).
- [ ] Social post drafted (X or LinkedIn, tagging `@GauntletAI`).
- [ ] Video uploaded unlisted to YouTube; link in `README.md`.
