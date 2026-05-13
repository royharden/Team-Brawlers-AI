# USERS — Who AgentForge Is For

## Introduction

AgentForge is a continuous, multi-agent adversarial security platform for AI-assisted clinical workflows. It exists because the way most health systems and EHR vendors test AI today does not work. The current state of practice is a security engineer with a notepad, a static list of jailbreak prompts that someone copied off X six months ago, and a quarterly penetration test report whose findings are validated once, filed in SharePoint, and never replayed against a model that has drifted three times since. That worked in a world where clinical software changed twice a year. It does not work in a world where a Clinical Co-Pilot's underlying model rolls forward every few weeks, its system prompt is tuned every sprint, its retrieval index ingests new PDFs every night, and the published-to-discovered window for novel prompt-injection techniques has collapsed from years to weeks.

The audience for AgentForge is the small but growing class of people inside health systems, EHR vendors, and clinical-AI startups whose job is to answer a single question on a recurring basis: **"Is it safe to ship the next version of this Co-Pilot to the next clinic?"** That question has three honest answers — yes, no, and "we don't have evidence either way" — and right now most teams are stuck in the third bucket. They cannot enumerate which attack categories they have covered. They cannot tell their CISO whether the system is getting safer or less safe over time. They cannot tell their product manager whether last sprint's safety fix held, regressed, or simply changed shape. They cannot tell their compliance officer which NIST AI RMF function the last quarter's testing maps to.

AgentForge is built to give those people defensible, reproducible, continuously-updated evidence. It does this by running four cooperating agents — an Orchestrator that decides what to test, a Red Team agent that generates and mutates attacks, an independent Judge that decides whether an attack succeeded, and a Documentation agent that converts every confirmed exploit into a structured `VR-####` vulnerability report and a deterministic regression case. Around those agents sits an observability layer (cost ledger, coverage matrix, Defense Delta over time, attack lineage trees) that makes the platform's behavior auditable to someone who was not in the room when an exploit was found.

The value proposition is three sentences long. **Discovery scales** because a mutation-driven Red Team agent can generate and try 10,000 variants of a partially-successful attack overnight, and a human cannot. **Findings persist** because every confirmed exploit becomes a deterministic test case that re-runs automatically whenever the target's fingerprint changes — git SHA, Docker image tag, sidecar `/healthz` hash. **Reports are defensible** because each `VR-####` carries an OWASP-LLM-Top-10 tag, an AVID tag, an AI-RMF mapping, a minimal reproducer, a discovery-replay history showing the attack failed before it succeeded, and a deterministic post-condition check that does not depend on a language model agreeing with itself. A hospital CISO reading those reports can defend the testing program to their board without taking AgentForge's word for any single verdict.

This document describes the four personas the platform is designed for, the workflows they perform inside it, the use cases that are explicitly out of scope, and an explicit justification — required by the PRD — for why automation is the right answer to this problem rather than more manual testing.

## Personas

### P1 — Hospital CISO (Dr. Maya Okafor, CISO, 1,200-bed regional health system)

**Goals**
- Decide whether to authorize the next clinic to enable the Clinical Co-Pilot.
- Produce defensible quarterly evidence for the board, the insurance carrier, and HHS auditors that AI-assisted workflows are being continuously stress-tested.
- Predict the cost of an ongoing AI-security program — not "what did we spend last month" but "what will we spend if we add three more AI features."
- Trust her own people. She does not want to outsource the question of "is this safe?" to a vendor.

**Pain points today**
- Receives a 60-page quarterly pentest PDF; cannot tell which findings still apply after the model version changed twice during the quarter.
- Cannot answer the board's question "are we getting safer or less safe?" with anything more than vibes.
- Has no cost ceiling on the testing program; engineers running ad-hoc frontier-model probes blow through the budget by mid-month with nothing reproducible to show for it.

**How AgentForge helps**
- The Coverage dashboard answers "which attack categories have we exercised, and at what pass rate?" in one screen.
- The Defense Delta chart answers "did this rev make the system safer or less safe?" with a number per target fingerprint.
- The Cost page answers "what will 10K test runs/month cost?" with a real telemetry-backed projection, not vendor marketing.
- Every `VR-####` report is structured the same way and carries the OWASP / AVID / NIST tags her auditors already know.

**Day in the life**
1. 8:30 AM — opens the AgentForge dashboard. Glances at the operator landing: target health green, last nightly run completed, two new HIGH-severity `VR-####` reports waiting for approval, daily spend at 31% of budget.
2. Clicks into the two new reports. Reads the clinical-impact paragraph, the minimal reproducer, and the discovery-replay history (three failed attempts before one succeeded — confirms this is a real intermittent exploit, not a sampling fluke).
3. Approves one for public disclosure to the engineering owners; flags the other "needs more eval" because the reproducer crosses a sensitive PHI boundary she wants legal to review first.
4. Opens the Defense Delta page. Notes that yesterday's target redeploy moved the score +0.08 — the model is mildly safer this rev. Marks the rev as cleared for the pilot clinic.
5. Closes the laptop. Total time: 14 minutes.

**Anti-persona — this is NOT for**
- Clinicians using the Co-Pilot directly. They never see AgentForge.
- General IT-security generalists looking for a network-pentest tool. AgentForge attacks the AI layer, not the network.

### P2 — Clinical-AI Application Security Engineer (Jordan Reyes, Senior AppSec Engineer)

**Goals**
- Run a continuous adversarial program against the Co-Pilot without becoming a full-time prompt-engineer.
- Convert every confirmed exploit into a regression test that fires forever, automatically, without further effort.
- Produce reports tagged with OWASP LLM Top 10, OWASP Agentic Top 10, AVID, and NIST AI RMF mappings — the taxonomies their auditors care about.

**Pain points today**
- Mutating attacks by hand is mind-numbing and they always miss the one mutation that lands.
- Their last "AI red-team report" was a Google Doc with screenshots. They cannot rerun it.
- They cannot tell whether the judge they used last quarter was scoring consistently with the judge they're using this quarter.

**How AgentForge helps**
- The Red Team agent mutates partially-successful attacks 10–50× per seed. **In this sprint** the Red Team runs on Anthropic Sonnet 4.6 with an authorized-pentest framing system prompt (see [AgDR-0001](agentdocs/decisions/AgDR-0001-redteam-on-anthropic-not-fireworks.md)); refusals are logged as `refusal_observed` and fed back into the Internal Progress Judge as mutation directives rather than treated as failures. A `REDTEAM_PROVIDER` config switch makes a future swap to Fireworks Dolphin a one-line change.
- The Judge agent maintains independence from the Red Team via model-family separation (Sonnet 4.6 for the External Final Judge vs Haiku 4.6/4.5 + deterministic detectors for the Internal Progress Judge), a deterministic floor (≥30% of judge load carried by `agentforge/judge/deterministic/*` modules untouched by any LLM), and a meta-eval gold set with ≥10 hand-labeled adversarial-against-judge cases. The cross-vendor variant of the original judge-independence rule is documented as relaxed in AgDR-0001; the per-class-import lint still enforces that judge code never imports from `agentforge.redteam.*`.
- Judge meta-eval re-runs against a 100-case human-labeled gold set and reports per-layer precision/recall/F1 — judge drift becomes a measurable, dashboard-visible signal, not a vibe.

**Day in the life**
1. Opens a terminal, runs `poetry run tb attack --category prompt_injection --strategy crescendo --count 30`.
2. Watches the Live Run page stream events: Orchestrator picks a coverage gap; Red Team generates 30 variants; Target Adapter calls the deployed Co-Pilot via `openemr_gateway`; Internal Judge gives near-miss feedback; External Judge issues final verdicts.
3. Three new `VR-####` drafts appear in the Vuln Reports page. Reviews the minimal reproducer for each. Approves two; rejects one as a known false positive and tags the rubric for tuning.
4. Approved reports auto-promote into `evals/regression/VR-####.json`. CI now re-runs them on every PR.
5. Runs `tb meta-eval --gold-set v1` weekly; if external-final F1 drops below the floor, raises an AgDR to retune rubrics before the next batch.

**Anti-persona — this is NOT for**
- People who want a one-click "scan my AI" tool with no engineering context. AgentForge expects an operator who can read a `VR-####` and reason about whether the reproducer is sound.

### P3 — EHR Vendor Product Manager (Priya Shah, PM, Clinical Co-Pilot feature team)

**Goals**
- Ship AI features without becoming the team that caused a PHI-leak headline.
- Get a CI signal that a PR makes the product safer (or at least no less safe) before merging.
- Have post-deployment evidence that the production model is still behaving as it did during pre-merge testing.

**Pain points today**
- Engineers "validate the fix" by trying the exact original payload, declaring victory, and merging. Three weeks later a variant of the same attack bypasses the fix.
- Has no automated gate that blocks a PR if it regresses a previously-fixed `VR-####`.
- Has no way to tell whether last month's model-version bump silently re-opened anything.

**How AgentForge helps**
- The regression harness (`tb regress --floor evals/floor.json`) runs in CI on every PR; merges blocked if any previously-passing case flips to fail.
- Target-fingerprint-driven re-runs fire automatically when the target git SHA, Docker image, or sidecar `/healthz` hash changes — no human has to remember to push a button after a redeploy.
- The Defense Delta Score gives a per-rev safety delta, not just a per-PR one, so model drift in production is visible.

**Day in the life**
1. Opens a PR titled "Add allergy-summary tool." CI runs `tb regress --floor` in mock-provider mode within 8 minutes.
2. PR shows the floor check passed; coverage gaps in `tool_misuse` are flagged as advisory (not blocking).
3. Merges. Deploy pipeline updates the Docker image tag; the Orchestrator detects the new target fingerprint within 60 seconds and re-runs the full regression suite against the live deployed target.
4. Nightly run finishes by 6 AM; Priya's Slack shows "0 new HIGH, 1 new MEDIUM in `tool_misuse`." She triages the medium next morning.

**Anti-persona — this is NOT for**
- PMs who want to ship without any safety gate at all. AgentForge is a guardrail; it will make PRs slower for the right reasons.

### P4 — Compliance / Risk Officer (optional persona) (Marcus Chen, Director of Regulatory Risk)

**Goals**
- Produce NIST AI RMF Govern / Map / Measure / Manage evidence for HHS and the insurance carrier.
- Demonstrate that AI-system risk management is continuous, not annual.

**Pain points today**
- Auditors ask "how do you Measure?" and the answer is a quarterly slide.
- AVID-tagged evidence is rare; auditors are starting to ask for it specifically.

**How AgentForge helps**
- Every `VR-####` carries OWASP-LLM-Top-10, OWASP-Agentic-Top-10, AVID, and NIST-AI-RMF tags pre-computed.
- The four RMF functions map cleanly: Govern → role/approval-gate config; Map → `THREAT_MODEL.md` + coverage matrix; Measure → Judge meta-eval + cost telemetry + regression floors; Manage → finding lifecycle, regression triggers, notifications, cost-without-signal halts.

**Anti-persona — this is NOT for**
- Compliance teams looking for a HIPAA audit replacement. AgentForge produces evidence; it does not replace the audit.

## Key Workflows

### W1 — Initial threat-model bootstrapping (one-time per target)

- **Trigger:** Operator onboards a new target Co-Pilot deployment.
- **Agents involved:** Operator (manual), Orchestrator (initial coverage matrix population), Red Team (seed batch).
- **Expected output:** `THREAT_MODEL.md` reviewed, seed attack catalog populated across nine categories, baseline coverage matrix populated.
- **Time to value:** ~2 hours (target stand-up + threat-model review) → first signal within an hour after that.

### W2 — Daily / nightly continuous attack run

- **Trigger:** Cron-scheduled nightly run or `tb attack --budget <USD>`.
- **Agents involved:** Orchestrator (selects coverage gaps + open-finding follow-ups), Red Team (generates + mutates), Target Adapter (executes against deployed Co-Pilot via `openemr_gateway`), Internal Judge (near-miss feedback), External Judge (final verdict), Documentation (drafts `VR-####` on confirmed fail), Budget Guard (halts on cost-without-signal).
- **Expected output:** Updated coverage matrix, ≥0 new draft `VR-####` reports queued for approval, refreshed cost ledger, refreshed Defense Delta.
- **Time to value:** First verdict <2 minutes after run start; full nightly run completes within the budget ceiling (typically 30–90 minutes).

### W3 — Target-fingerprint-change-triggered regression replay

- **Trigger:** Orchestrator detects a change in the composed target fingerprint (URL + sidecar `/healthz` body hash + Docker image tag + target git SHA).
- **Agents involved:** Orchestrator (detects + enqueues), Regression harness (replays), External Judge (re-verdicts), Notifier (alerts on regression).
- **Expected output:** Full regression suite re-runs before any new exploratory work; previously-passing cases flipping to fail emit a `regression_failure` notification.
- **Time to value:** Detection within 60 seconds of redeploy; full regression sweep typically <15 minutes.

### W4 — New-vulnerability triage flow

- **Trigger:** External Judge confirms a fail (`verdict.layer == "external_final"` AND `verdict.adapter_mode == openemr_gateway`).
- **Agents involved:** Documentation (writes draft `VR-####`), Notifier (Slack/email on `severity >= HIGH`), Operator (human approval gate for HIGH+).
- **Expected output:** Structured `VR-####` markdown with severity, OWASP/AVID/NIST tags, clinical impact, minimal reproducer, observed-vs-expected, recommended remediation, fix status. Sidecar-only findings stay quarantined as `sidecar_diagnostic`.
- **Time to value:** Draft report ready within ~60 seconds of judge verdict; operator approval typically within a working day.

### W5 — Fix validation

- **Trigger:** Engineering owner pushes a fix; target fingerprint changes; W3 fires automatically.
- **Agents involved:** Regression harness, External Judge, Orchestrator (updates `VR-####.status` from `open` → `fixed` only after the regression case passes), Defense Delta calculator.
- **Expected output:** `VR-####` lifecycle advances from `open` → `fixed`; Defense Delta increments positively for that fingerprint; the case stays in the regression suite forever so a future regression flips it back.
- **Time to value:** Same redeploy cycle as W3 — typically <15 minutes from fix-deploy to validated.

### W6 — Cost-budget overrun investigation

- **Trigger:** Budget Guard halts the current run because cost-without-signal threshold was crossed (spend climbing, no new verdicts landing).
- **Agents involved:** Budget Guard (halts), Operator (reviews), Attack Lineage Map (renders the run's seed → mutation tree).
- **Expected output:** Operator opens the Attack Lineage page, identifies the mutator chain or category that burned spend without finding signal, opens an AgDR to either deprioritize that strategy or tune the prompt that ballooned tokens. Run is resumed (or not) only after a deliberate decision.
- **Time to value:** Halt is instantaneous; operator review typically <30 minutes.

## Why Automation

The PRD explicitly requires this section. The five-part justification:

1. **Scale — mutation space is combinatorial.** A single seed attack has on the order of 10⁴–10⁶ plausible variants when you cross direct/indirect/multi-turn × persona × encoding × payload × tool-context. No human enumerates that space. The Red Team agent samples it intelligently, prioritized by partial-success signal.

2. **Regression — every confirmed exploit becomes a deterministic test.** A bug found once and not converted into an automated test will recur. AgentForge converts every gateway-replayed `VR-####` into a `evals/regression/VR-####.json` with mutator chain, seed integer, model resolution, rubric version, and deterministic post-conditions — replayable on every target-fingerprint change forever.

3. **Adaptation — target models drift; static lists go stale.** Co-Pilot underlying models, system prompts, and retrieval indices change continuously. A static attack list authored against last quarter's model version is, within weeks, mostly testing for behaviors the model no longer exhibits. The Red Team agent regenerates and mutates against the current target every run.

4. **Cost — deterministic-first judging beats frontier-everywhere by ~90%.** Naive "use Claude Opus to judge everything" approaches cost an order of magnitude more than the AgentForge architecture, which routes deterministic post-conditions and rubric-based scoring to deterministic verifiers + Haiku-class judges, escalating to Sonnet only for ambiguous or HIGH-severity cases. The cost ledger makes that savings visible per-run and per-category.

5. **Trust boundaries — explicit, listed, human-in-the-loop where it matters.** Automation is not "remove the human" — it is "remove the human from the parts where humans add no value, and keep them where they do." The human approval gates are explicit:
   - **HIGH+ severity `VR-####` requires operator approval** before it leaves the `sidecar_diagnostic` quarantine or is shared outside the security team.
   - **Floor changes to `evals/floor.json` require an AgDR.** No silent floor erosion.
   - **Public disclosure of any `VR-####`** is an operator action, not an agent action.
   - **Budget halts are reviewed by a human** before a run resumes.
   - **Sidecar-direct findings never auto-promote.** Only `openemr_gateway` external-final verdicts can become public `VR-####` reports.

## Use Cases NOT In Scope

- **Generic OpenEMR penetration testing** (SQLi, XSS, RCE against the non-AI surface). Use a traditional web-app scanner; AgentForge attacks the AI layer.
- **Fuzzing of non-AI surfaces** (REST endpoints with no LLM in the loop). Same — wrong tool.
- **Social engineering of staff.** AgentForge attacks software, not people.
- **Compliance-audit replacement.** AgentForge produces evidence usable in an audit; it does not certify compliance with HIPAA, HITRUST, or any other framework.
- **Production attacks against real patient data.** Every fixture is synthetic; `TARGET_ALLOWLIST` blocks any URL not on the approved list; PHI scrubbers strip incidental real-looking identifiers from observability output.
- **Attacks against arbitrary third-party LLMs.** The platform is built around the OpenEMR Clinical Co-Pilot target adapter; extending to other targets is future work.

## Operator Commands

| Command | One-line description | Typical user role |
|---|---|---|
| `tb smoke` | Run a tiny fixed-budget smoke test against the target adapter. Confirms the platform-target loop is alive. | All operators; CI; demo. |
| `tb attack --category <c> --strategy <s> --count <n>` | Run a focused exploratory attack batch. Used for hunting and category-specific deep dives. | AppSec Engineer (P2). |
| `tb regress` (`--case`, `--since-fingerprint`, `--floor`) | Replay the regression suite — all cases, one case, only cases stale against the current target fingerprint, or as a CI floor gate. | AppSec Engineer (P2); PM (P3) via CI; Orchestrator agent (automated). |
| `tb report` | Generate or refresh the public `VR-####` report index from confirmed external-final findings. | AppSec Engineer (P2); CISO (P1) for review. |
| `tb meta-eval --gold-set <v>` | Re-run the judge against the human-labeled gold set; emit per-layer precision/recall/F1/Krippendorff α. | AppSec Engineer (P2); Compliance (P4) for evidence. |
| `tb seed` | Inspect or add to the seed-attack catalog; validate seed files against the case schema. | AppSec Engineer (P2). |

All commands are budget-aware (every run honors `BUDGET_*` env-var ceilings) and emit structured events to the Live Run page on the dashboard so a non-CLI operator can watch the same activity in the UI.
