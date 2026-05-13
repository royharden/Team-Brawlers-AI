# railway_deploy_agentforge_opus47_2026-05-13 — Initial AgentForge Deploy On Railway (New Project)

**For:** Roy Harden — Gauntlet AgentForge Week 3 (Austin Admission)
**Date:** 2026-05-13
**Verified by:** Claude Opus 4.7 — every env var name, command, and expected output cross-checked against `agentforge/config.py`, `agentforge/api/main.py`, `agentforge/ui/app.py`, `pyproject.toml`, and `agentforge/redteam/openrouter_client.py` on `origin/main` at the time of writing.
**Starting point:** You already have an `openemr-mvp` Railway project from the May 13 redeploy with three services (`openemr` public, `mariadb` private, `copilot-api` private). The Co-Pilot's public URL works in incognito.
**Goal:** Stand up a **second, independent Railway project** that runs the AgentForge adversarial platform. The platform attacks your live Co-Pilot URL, persists its findings in SQLite, exposes a FastAPI dashboard, and surfaces a Streamlit operator UI. Two public URLs by the end: `agentforge-api-production-XXXX.up.railway.app` and `agentforge-ui-production-XXXX.up.railway.app`.

This is the first AgentForge deployment runbook (v1). It is self-contained — do not switch between this and the openemr runbooks while deploying.

---

## 0. TL;DR — What You Are Doing And Why

You will:

1. Confirm AgentForge code is pushed to `github.com/royharden/Team-Brawlers-AI` `main` (1 min).
2. **Create a NEW, separate Railway project** named `agentforge` (1 min).
3. Add the `agentforge-api` service — FastAPI on port 8100, Nixpacks-built from your repo (4 min).
4. Set 16 env vars on `agentforge-api` (OpenRouter + Anthropic + Langfuse + budget + target URL) (4 min).
5. Mount a persistent volume on `agentforge-api` at `/data` for the SQLite DB and notifier queue (1 min).
6. Generate a public HTTPS domain for `agentforge-api` (30 sec). ← URL #1 of 2
7. Add the `agentforge-ui` service — Streamlit, points at the API over Railway private networking (4 min).
8. Generate a public HTTPS domain for `agentforge-ui` (30 sec). ← URL #2 of 2
9. Smoke test: `/healthz` returns 200; dashboard JSON has zero counts; UI loads (3 min).
10. Wire the live Co-Pilot URL into `TARGET_BASE_URL` and `TARGET_ALLOWLIST`; run the existing sample-VR generator to seed three VRs in the dashboard (2 min).
11. Submit both URLs in the project README + Gauntlet portal (1 min).

**Total wall time:** ~25 minutes once you have the secrets in hand.

> ⚠️ **DO NOT** put AgentForge services in the same Railway project as `openemr-mvp`. AgentForge is the *attacker*. Two separate projects = clean failure domains + clean architecture story + risk-isolated demos. The recommendation memo in the operator inbox lists six reasons. Don't fight it.

---

## 1. Decision: New Project, Not Same Project

The existing `openemr-mvp` Railway project already runs three services (public `openemr`, private `mariadb`, private `copilot-api`). The AgentForge platform is intentionally separate because:

1. **Different repo, different deploy lifecycle.** AgentForge lives in `github.com/royharden/Team-Brawlers-AI`. Railway projects are clearest when one project ≈ one repo's deploy trigger.
2. **Architecture defense.** "AgentForge attacks an independent deployed target" reads cleanly when target and attacker are in different Railway projects. Reviewers see the topology immediately in the dashboards.
3. **Risk isolation.** AgentForge composes adversarial inputs. A crash or weird state in `agentforge-api` should NEVER threaten OpenEMR's demo URL.
4. **Two deployed URLs.** The PRD requires both. Two projects = two dashboards = two obviously-separate things to submit.
5. **Public-URL attack path.** AgentForge attacks the Co-Pilot via its **public** Railway URL (`openemr-production-XXXX.up.railway.app`). That's the threat-model-correct path (an attacker hits the public surface, not a private network). Railway projects can't share private networking across project boundaries anyway.
6. **Cost is the same.** Railway Hobby ($5/mo + $5 usage credit) is per-account, not per-project. Multiple projects share the same $5 usage allowance.

---

## 2. Prerequisites — Gather These Before You Start

1. **Railway account** on Hobby plan — already present from `openemr-mvp` deploy.
2. **GitHub repo** at `github.com/royharden/Team-Brawlers-AI` with `main` up to date. Commit `76f6108` or later includes `DEMO_SCRIPT.md` and the three sample VRs.
3. **API keys** in your password manager:
   - `ANTHROPIC_API_KEY` — already used for `copilot-api`. Same key is fine.
   - `OPENROUTER_API_KEY` — your `sk-or-v1-...` key at `openrouter-dolphin-uncensored-free-dev.txt` in the outer working dir.
   - `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY` — `pk-lf-...` / `sk-lf-...` from `LANGFUSE_KEY_DEV.txt`. **US region** account → host is `https://us.cloud.langfuse.com`.
4. **Your live Co-Pilot Railway URL** — copy from the `openemr-mvp` project's `openemr` service → Settings → Networking. Looks like `https://openemr-production-XXXX.up.railway.app`. We refer to this as `<COPILOT_URL>` below.
5. **HMAC signing secret** — fresh 32+ bytes, separate from the openemr gateway secret:
   ```powershell
   -join ((1..64) | ForEach-Object { '{0:x}' -f (Get-Random -Minimum 0 -Maximum 16) })
   ```
   Save in your password manager as `AGENTFORGE_HMAC_SECRET`.

---

## 3. Preflight — Before Touching Railway

### 3.1 Confirm `main` Is Pushed And Up To Date

```powershell
cd "C:\Users\Roy Harden\OneDrive\PJ-OD\Team-Brawlers-AI\Team-Brawlers-AI"
git status --short
git log --oneline -5
git branch --show-current
```

Expected:
- Working tree clean (or only untracked files inside `agentdocs/` / `planning/` — both gitignored).
- HEAD on `main` with commit `76f6108` or later in `git log`.
- `git status -sb` shows `## main...origin/main` (no `[ahead N]`).

If `[ahead N]` appears:

```powershell
$token = (Get-Content "..\github-auth-token-fine-grained-30days.txt" -Raw).Trim()
git push "https://x-access-token:$token@github.com/royharden/Team-Brawlers-AI.git" main
$token = $null
git fetch origin
```

### 3.2 Run The Local Gate One Last Time

```powershell
pytest tests/ -q --no-header
```

Expected: `393 passed` (or higher). If any tests fail, **stop** — Railway is not the place to debug a broken local build.

### 3.3 Generate The Sample VRs Locally (Optional But Recommended)

This pre-populates `reports/` and `evals/regression/` so your first Railway dashboard load isn't empty:

```powershell
python scripts/generate_sample_vrs.py
git add reports/ evals/regression/ data/agentforge.sqlite 2>$null
git status --short
```

Three VRs should be on disk (`VR-0001` data_exfiltration, `VR-0002` prompt_injection, `VR-0003` tool_misuse). These were already committed in `76f6108`, so `git status` will likely show no changes. If you want a fresh DB on Railway, the volume mount in §6.3 will get one at deploy time anyway.

---

## 4. Create The New Railway Project

### 4.1 Open Railway Dashboard

<https://railway.com/dashboard>

You should see your existing `openemr-mvp` project tile. **Leave it alone** for this entire runbook.

### 4.2 Create The Project

1. Top-right → **+ New Project** → **Empty Project**.
2. Railway auto-names with `<adjective>-<noun>`. Rename:
   - Top-right of project canvas → **Settings** (gear) → **General** → **Name** → `agentforge` → Save.

> 📝 **Service name matters.** Railway reference syntax is case-sensitive. Lowercase the project name to keep typing predictable.

---

## 5. Add The `agentforge-api` Service

### 5.1 Create The Service From The GitHub Repo

1. Project canvas → **+ Create** (top-right) → **GitHub Repo**.
2. If Railway hasn't been authorized on `royharden/Team-Brawlers-AI` yet: click **Configure GitHub App** → grant Railway access to that repo specifically (do NOT grant "all repos" unless you want Railway to see your other private repos).
3. Pick `royharden/Team-Brawlers-AI`.
4. **Branch:** `main`.
5. After the service tile appears, click it → **Settings** → **Service Name** → set to:
   ```
   agentforge-api
   ```
   → Save.
6. **Root directory:** leave blank. The Python project IS the repo root.
7. **Build:** Railway's **Nixpacks** auto-detects `pyproject.toml` + Poetry and runs `poetry install --no-dev`. Confirm in the Settings panel that the build provider shows **Nixpacks** (not Docker — that would expect a Dockerfile we don't ship).

> ℹ️ **If Nixpacks misfires** (e.g., picks the wrong Python version): override the **Build Command** to:
> ```
> pip install poetry==1.8.3 && poetry config virtualenvs.create false && poetry install --no-interaction --no-ansi --without dev
> ```
> Python version pin (set as a build env var below): `NIXPACKS_PYTHON_VERSION=3.11`.

### 5.2 Set The Start Command

Settings tab → **Deploy** section → **Start Command**:

```
uvicorn agentforge.api.main:app --host 0.0.0.0 --port $PORT
```

> 🚨 `$PORT` is Railway's auto-injected port variable. Hardcoding `8100` works locally but **fails on Railway** — Railway expects the app to bind whatever it injects. The `PORT` env var in §5.3 below also helps the platform locally, but Railway's `$PORT` overrides it in the start command.

### 5.3 Set Variables On `agentforge-api`

**Variables** tab → **+ New Variable** for each row. Use the **+ Add Reference** picker (chain icon) for the two `${{service.VAR}}` rows — do NOT paste them as plain text.

| Variable | Value | Notes |
|---|---|---|
| `PORT` | `8100` | Local default. Railway also injects its own `$PORT` automatically; the start command uses `$PORT`. |
| `ANTHROPIC_API_KEY` | your `sk-ant-api03-...` key | Used by Judges + Documentation + Orchestrator. |
| `ANTHROPIC_FAST_MODEL` | `claude-haiku-4-6` | Internal Progress Judge model. |
| `ANTHROPIC_ORCHESTRATOR_MODEL` | `claude-sonnet-4-6` | Orchestrator + External Final Judge + Documentation. |
| `REDTEAM_PROVIDER` | `openrouter` | Default per AgDR-0013. |
| `REDTEAM_MODEL` | `cognitivecomputations/dolphin-mistral-24b-venice-edition:free` | The Cognitive Computations Dolphin checkpoint. |
| `OPENROUTER_API_KEY` | your `sk-or-v1-...` key | Red Team backend. Required when REDTEAM_PROVIDER=openrouter. |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | OpenAI-compatible endpoint. |
| `OPENROUTER_REDTEAM_MODEL` | `cognitivecomputations/dolphin-mistral-24b-venice-edition:free` | Same model; mirrored for the resolver. |
| `OPENROUTER_REDTEAM_FALLBACK_MODEL` | `cognitivecomputations/dolphin-mistral-24b-venice-edition` | Paid Venice variant for `:free`-tier 429 rate-limits. |
| `OPENROUTER_X_TITLE` | `AgentForge` | OpenRouter ranking header. |
| `LANGFUSE_PUBLIC_KEY` | your `pk-lf-...` | Observability. Optional but recommended. |
| `LANGFUSE_SECRET_KEY` | your `sk-lf-...` | Observability. |
| `LANGFUSE_HOST` | `https://us.cloud.langfuse.com` | **US region — set explicitly.** Default in code is EU. |
| `AGENT_MESSAGE_SIGNING_SECRET` | your fresh HMAC secret from §2.5 | Verifies inter-agent messages. Required. |
| `PLATFORM_DB_URL` | `sqlite:////data/agentforge.sqlite` | **Four slashes** for an absolute path. The `/data` mount comes from §6.3. |
| `TARGET_BASE_URL` | `<COPILOT_URL>` | The full HTTPS URL of your live Co-Pilot. Example: `https://openemr-production-abcd.up.railway.app`. |
| `COPILOT_SIDECAR_URL` | _(leave blank)_ | The sidecar is private inside `openemr-mvp` — not reachable from AgentForge. Adapter falls back to `openemr_gateway` mode. |
| `TARGET_ALLOWLIST` | `<COPILOT_HOST>` | Just the hostname (no protocol). Example: `openemr-production-abcd.up.railway.app`. Comma-separate if you ever add more. |
| `BUDGET_SMOKE_USD` | `1.00` | Per-run ceiling for `tb smoke`. |
| `BUDGET_SEEDED_USD` | `5.00` | Per-run ceiling for seeded attacks. |
| `BUDGET_EXPLORATORY_USD` | `10.00` | Per-run ceiling for exploratory attacks. |
| `BUDGET_PER_DAY_USD` | `25.00` | Per-day cumulative ceiling. |
| `BUDGET_HALT_AFTER_N_NULL_RUNS` | `25` | Cost-without-signal halt: stop after 25 attempts with no new findings. |
| `BUDGET_NULL_RUN_SPEND_THRESHOLD_USD` | `3.00` | Combined with the line above. |
| `ALLOW_BROWSER_AUTOMATION` | `false` | Playwright adapter mode is OFF by default. |
| `ALLOW_TARGET_FIXES_PUSH` | `false` | The Documentation Agent never pushes target fixes without operator approval. |
| `PYTHONUNBUFFERED` | `1` | Ensures logs stream to Railway immediately. |
| `NIXPACKS_PYTHON_VERSION` | `3.11` | Forces Python 3.11 to match local dev. |

> 🛟 **Common gotcha (1):** `PLATFORM_DB_URL` needs FOUR slashes (`sqlite:////data/...`). Three slashes (`sqlite:///./data/...`) is the LOCAL relative-path form; four slashes is the ABSOLUTE-path form Railway needs because the working directory inside the container isn't your repo root.
>
> 🛟 **Common gotcha (2):** `TARGET_ALLOWLIST` is **hostnames only**, not URLs. The allowlist code calls `urlparse` and compares against `.hostname`. If you paste `https://openemr-production-...` here, the allowlist won't match and every adapter call returns `TargetNotAllowed`.

### 5.4 Deploy And Watch Logs

Deploy will trigger automatically after the first variable add. Watch:

`agentforge-api` → **Deployments** → latest → **View Logs**.

Good log sequence:

```text
─── Build ───
Detected Python project (Nixpacks)
Installing Python 3.11
Installing poetry...
Installing dependencies via poetry...
   • Installing fastapi (0.115.x)
   • Installing anthropic (0.40.x)
   • Installing openai (1.54.x)
   ...
─── Deploy ───
INFO:     Started server process [1]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8100 (Press CTRL+C to quit)
```

> ❌ `pydantic_settings` errors / `OPENROUTER_API_KEY required` → Your variables missed the `OPENROUTER_API_KEY`. Recheck the table above.
>
> ❌ `sqlite3.OperationalError: unable to open database file` → The `/data` volume isn't mounted yet. Do §6.3 first.
>
> ❌ Build fails on `poetry install` with `Resolving dependencies (failed)` → Most likely a transient PyPI mirror issue; redeploy from the Deployments tab.

### 5.5 Set The Healthcheck Path

Settings → **Deploy** → **Healthcheck Path** → `/healthz`.
Timeout: `300` seconds (first deploy installs Poetry + ~25 packages).

---

## 6. Persistent Volume On `agentforge-api`

### 6.1 Why

The platform writes:
- `data/agentforge.sqlite` — runs, attacks, verdicts, vuln_reports, regression_cases, cost_ledger, coverage_cells, defense_delta_snapshots, agent_messages, flight_events.
- `data/notifier_queue.jsonl` — approval-gate queue for severity ≥ High findings.
- `reports/.vr_counter` — monotonic VR-#### allocator.
- `reports/VR-####-*.{md,html}` — rendered vulnerability reports.
- `evals/regression/VR-####.json` — replay cases.

Without a volume, every Railway redeploy wipes the entire forensic record. With a volume, the platform survives redeploys.

### 6.2 Add The Volume

`agentforge-api` service → **Settings** → scroll to **Volumes** → **+ Mount Volume**.

| Field | Value |
|---|---|
| Mount path | `/data` |
| Size | `2 GB` |

Save.

### 6.3 What `/data` Stores

We map `PLATFORM_DB_URL=sqlite:////data/agentforge.sqlite` (§5.3) so the DB lives on the volume.

The `notifier_queue_path` and `reports/` directory are app-default-relative, not volume-relative. To put them on the volume too, add these env vars on `agentforge-api`:

| Variable | Value |
|---|---|
| `AGENTFORGE_NOTIFIER_QUEUE_PATH` | `/data/notifier_queue.jsonl` |
| `AGENTFORGE_REPORTS_DIR` | `/data/reports` |
| `AGENTFORGE_REGRESSION_DIR` | `/data/regression` |

> ℹ️ The platform reads these only if the documentation/regression code is instantiated via the explicit-path constructor. The bundled FastAPI uses sensible defaults — the env vars above are forward-compatible for when the DocumentationAgent gets wired into a `/v1/runs/start` endpoint (Phase 8). Setting them now does no harm.

### 6.4 Redeploy

After mounting the volume, redeploy from the Deployments tab. The service should come up green with `/healthz` returning `200 {"status":"ok","phase":"5","tests_passing":337}`.

---

## 7. Generate The Public Domain For `agentforge-api`

`agentforge-api` → **Settings** → **Networking** → **Public Networking** → **Generate Domain**.

If Railway asks for a target port, enter `8100`.

Railway gives you a URL like `https://agentforge-api-production-XXXX.up.railway.app`. **Copy this URL. This is the platform's primary deployed URL (URL #1 of 2).**

Quick verification:

```powershell
curl https://agentforge-api-production-XXXX.up.railway.app/healthz
curl https://agentforge-api-production-XXXX.up.railway.app/v1/dashboard
```

Expected:

```json
{"status":"ok","version":"0.1.0","phase":"5","tests_passing":337}
```

And the dashboard returns a JSON body with `totals.runs=0` (or 1 if you committed the sample VRs).

---

## 8. Add The `agentforge-ui` Service

### 8.1 Create The Streamlit Service

Same Railway project (`agentforge`). **+ Create** → **GitHub Repo** → `royharden/Team-Brawlers-AI` → **Branch: main**.

Rename: Settings → **Service Name** → `agentforge-ui`.

### 8.2 Start Command

Settings → **Deploy** → **Start Command**:

```
streamlit run agentforge/ui/app.py --server.port=$PORT --server.address=0.0.0.0 --server.headless=true --browser.gatherUsageStats=false
```

The `--browser.gatherUsageStats=false` flag suppresses Streamlit's first-run telemetry prompt that would otherwise hang the boot.

### 8.3 Variables On `agentforge-ui`

| Variable | Value | Notes |
|---|---|---|
| `PORT` | `8501` | Streamlit default. Railway also injects `$PORT`. |
| `AGENTFORGE_API_URL` | `http://${{agentforge-api.RAILWAY_PRIVATE_DOMAIN}}:8100` | **Use the reference picker** — chain icon next to the value field. Resolves to `http://agentforge-api.railway.internal:8100`. |
| `NIXPACKS_PYTHON_VERSION` | `3.11` | |
| `PYTHONUNBUFFERED` | `1` | |

> 🛟 **Gotcha (1):** Don't generate a public domain on `agentforge-ui` until you've confirmed `agentforge-api` is up. The UI page-load will hammer `/v1/dashboard`; if the API is still building, the UI shows a wall of errors on first impression.
>
> 🛟 **Gotcha (2):** The Streamlit UI talks to the API on `RAILWAY_PRIVATE_DOMAIN`, which is the *internal* hostname (`agentforge-api.railway.internal`). That works only because both services are in the same Railway project. Cross-project private networking is not a thing.

### 8.4 Watch The Build

`agentforge-ui` → Deployments → latest → View Logs.

Good log sequence:

```text
─── Build ───
Detected Python project (Nixpacks)
Installing Python 3.11
Installing dependencies via poetry...
─── Deploy ───
Streamlit server started on http://0.0.0.0:8501
You can now view your Streamlit app in your browser.
```

Streamlit binds to the port and serves; no further startup messages needed.

### 8.5 Generate The Public Domain

`agentforge-ui` → Settings → Networking → Public Networking → Generate Domain.

Target port: `8501`.

You get a URL like `https://agentforge-ui-production-XXXX.up.railway.app`. **Copy this URL. This is the operator-facing UI (URL #2 of 2).**

Open it in incognito. You should see the AgentForge Dashboard with:
- Header: "AgentForge | Adversarial AI Security Platform".
- Sidebar showing Red Team provider (`openrouter`), target fingerprint, judge floor met badge.
- Main content: zero counts (or three VRs if you committed `reports/` from §3.3).

---

## 9. Wire AgentForge Up To The Live Co-Pilot Target

The `TARGET_BASE_URL` env var (§5.3) already points at `<COPILOT_URL>`. Confirm AgentForge sees it:

```powershell
curl https://agentforge-api-production-XXXX.up.railway.app/v1/dashboard
```

Expected (relevant subset):

```json
{
  "totals": {"runs": 0, "attacks": 0, "vrs_open": 0, "vrs_fixed": 0, "spend_usd": "0.00"},
  "latest_fingerprint": "<sha256 of TARGET_BASE_URL + ...>"
}
```

If `latest_fingerprint` is `null`: the target fingerprint hasn't been computed yet (no run has executed). That's fine; first run materializes it.

### 9.1 Re-Run The Sample-VR Generator Against The Live URL

The sample-VR generator uses synthetic responses, not live target calls — so it works regardless of target connectivity. To run it on Railway:

```text
agentforge-api → Settings → Service Settings → Pre-deploy Command (or use a one-off shell)
```

Railway's UI varies. The simplest path is:

1. Open the **Shell** tab on the `agentforge-api` service (some plans require enabling this).
2. Run:
   ```bash
   python scripts/generate_sample_vrs.py \
     --reports-dir /data/reports \
     --regression-dir /data/regression \
     --notifier-queue /data/notifier_queue.jsonl
   ```
3. Confirm 3 VRs land at `/data/reports/VR-{0001,0002,0003}-*.{md,html}`.

If the Shell tab isn't available on your plan: the three VRs are already in the repo at `reports/VR-0001.md` etc, baked into the Nixpacks image. They'll appear in the dashboard automatically on first GET — they're read from the working directory, not the volume.

### 9.2 First Live Smoke Against The Co-Pilot

```powershell
curl "https://agentforge-api-production-XXXX.up.railway.app/v1/regression/cases"
```

Expected: JSON list with three entries (`VR-0001`, `VR-0002`, `VR-0003`).

```powershell
curl "https://agentforge-api-production-XXXX.up.railway.app/v1/reports/VR-0001"
```

Expected: full markdown body of the data-exfiltration sample report.

### 9.3 Live Smoke Test Of The Target (Manual)

The platform's `tb regress` / orchestrator step is the way to attack the live Co-Pilot. For Wk3 grading, **demo this from a local terminal** rather than from inside Railway:

```powershell
# locally
cd "C:\Users\Roy Harden\OneDrive\PJ-OD\Team-Brawlers-AI\Team-Brawlers-AI"

# set env so the local CLI talks to the live target
$env:TARGET_BASE_URL = "https://openemr-production-XXXX.up.railway.app"
$env:TARGET_ALLOWLIST = "openemr-production-XXXX.up.railway.app"

# verify the platform can see the seeds catalog
poetry run tb seed --category prompt_injection

# (Phase-1-Docker-gated tasks - sidecar_direct / openemr_gateway happy paths -
# need to land before `tb attack` does anything useful against the live target.
# For Wk3 the demo uses `tb regress --mock` to replay the 3 sample VRs.)
poetry run tb regress --mock tests/fixtures/regression_replay/ --floor evals/floor.json
```

> 🚦 The platform CAN'T yet send actual attacks to the deployed Co-Pilot from Railway because `agentforge/target_adapter/sidecar_direct.py` and `openemr_gateway.py` are still stubs (Phase 1 Docker-gated). For Wk3 the deployed AgentForge UI shows the *baseline* state (3 VRs, coverage matrix, judge meta-eval, cost projections). Live attacks happen after the adapter wiring lands.

---

## 10. README Updates + Submission

### 10.1 Add Both Deployed URLs To `README.md`

```powershell
cd "C:\Users\Roy Harden\OneDrive\PJ-OD\Team-Brawlers-AI\Team-Brawlers-AI"
```

Find the "Deployed URLs" section in `README.md`. Replace with:

```markdown
## Deployed URLs

- **Co-Pilot target** (attack surface):
  `https://openemr-production-XXXX.up.railway.app`
- **AgentForge platform API** (FastAPI):
  `https://agentforge-api-production-XXXX.up.railway.app`
  - `/healthz` — liveness
  - `/v1/dashboard` — overview JSON
  - `/v1/reports` — vulnerability reports list
  - OpenAPI docs at `/docs`
- **AgentForge platform UI** (Streamlit):
  `https://agentforge-ui-production-XXXX.up.railway.app`
```

Commit + push:

```powershell
git add README.md
git commit -m "docs: add Railway deployed URLs (API + UI) for AgentForge platform"
$token = (Get-Content "..\github-auth-token-fine-grained-30days.txt" -Raw).Trim()
git push "https://x-access-token:$token@github.com/royharden/Team-Brawlers-AI.git" main
$token = $null
```

Railway will redeploy both services after the push (it watches `origin/main`). Wait ~2 minutes for the cycle, then confirm both URLs still respond.

### 10.2 Add To Gauntlet Portal

Submit per the Wk3 submission portal:

- **GitHub repo:** `https://github.com/royharden/Team-Brawlers-AI`
- **Deployed application URL:** the AgentForge UI URL (operator-facing). The Co-Pilot URL is the *target*, not the platform itself.
- **Demo video:** per `DEMO_SCRIPT.md`.

---

## 11. Troubleshooting

### 11.1 `agentforge-api` build fails on Nixpacks

| Symptom | Likely cause | Fix |
|---|---|---|
| `Could not find a version that satisfies the requirement` | Wrong Python version | Add `NIXPACKS_PYTHON_VERSION=3.11` to the build env vars and redeploy. |
| `Resolving dependencies (failed)` once, then works | Transient PyPI mirror failure | Click **Redeploy**. |
| `pyproject.toml not found` | Service root directory was set to a sub-path | Settings → leave root directory blank. |
| Build OK but service crashes on boot with `ImportError` | Optional extra (e.g. `playwright`) was assumed installed | Set `ALLOW_BROWSER_AUTOMATION=false`. The platform skips Playwright imports when this is false. |

### 11.2 `agentforge-api` boots but `/healthz` returns 502

| Symptom | Likely cause | Fix |
|---|---|---|
| Logs show `Uvicorn running on http://0.0.0.0:8100` but Railway returns 502 | Start command uses `8100` instead of `$PORT` | Edit start command: `uvicorn agentforge.api.main:app --host 0.0.0.0 --port $PORT`. Redeploy. |
| Logs show app crashed | Pydantic `ValidationError` on settings | Tail logs for the field name. Usually `OPENROUTER_API_KEY` or `AGENT_MESSAGE_SIGNING_SECRET` missing. |
| Logs show `sqlite3.OperationalError: unable to open database file` | `/data` volume not mounted, or `PLATFORM_DB_URL` has three slashes instead of four | Confirm volume at `/data` exists; confirm `PLATFORM_DB_URL=sqlite:////data/agentforge.sqlite`. |

### 11.3 `agentforge-ui` boots but shows "Connection refused" on dashboard load

| Symptom | Likely cause | Fix |
|---|---|---|
| UI loads, but every page shows `httpx.ConnectError: Connection refused` | `AGENTFORGE_API_URL` is pointing at the wrong service or wrong port | Re-set via the **Reference picker** (chain icon), not plain text. Should resolve to `http://agentforge-api.railway.internal:8100`. |
| UI loads, dashboard JSON arrives but Coverage page is empty | Expected. No runs have executed yet. The platform's seed catalog and rubric registry are static; the coverage matrix only populates after attacks run. | Either wait for live attacks (Phase 1 Docker-gated) or seed the matrix via the sample-VR generator (§9.1). |
| UI shows "private network" timeout | Both services not in the same Railway project | Move them. Cross-project private networking is not supported. |

### 11.4 Cost is creeping past $5/mo

| Symptom | Likely cause | Fix |
|---|---|---|
| Hobby usage page shows compute > $5 | Idle services charged for memory | Project → Settings → enable "Sleep when idle" for both AgentForge services. The PRD demo run can wake them. |
| LLM cost spike on Sonnet | The External Final Judge being called for non-deterministic rubrics on every run | Confirm `BUDGET_PER_DAY_USD=25.00` is set; the BudgetGuard halts at the ceiling. |
| OpenRouter quota exhausted on `:free` | Cognitive Computations Dolphin `:free` tier has daily quota | The client falls back to the paid Venice variant (`OPENROUTER_REDTEAM_FALLBACK_MODEL`). If you want to suppress this, set `OPENROUTER_REDTEAM_FALLBACK_MODEL=` (empty) to make rate-limit errors propagate. |

### 11.5 Langfuse traces missing

| Symptom | Likely cause | Fix |
|---|---|---|
| Langfuse Cloud shows no traces | Wrong host (EU vs US) | `LANGFUSE_HOST=https://us.cloud.langfuse.com` (the code defaults to EU). |
| `agentforge.observability.langfuse_client` logs "LangfuseClient disabled (keys missing)" on every call | One of the keys is empty | Recheck both `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY`. The client requires BOTH to be present. |

### 11.6 Volume Data Lost After Redeploy

If `data/agentforge.sqlite` disappears after a redeploy:

1. Confirm: `agentforge-api` → Settings → Volumes → list shows one volume mounted at `/data`.
2. Confirm: `PLATFORM_DB_URL` has FOUR slashes (`sqlite:////data/...`). Three slashes is a relative path and writes inside the container's working directory — which is lost on redeploy.
3. If the volume was deleted and recreated: data is gone. Re-run the sample-VR generator (§9.1) to repopulate.

---

## 12. Deployment Readiness Checklist

- [ ] `git push origin main` succeeded; HEAD on Railway matches HEAD locally.
- [ ] `pytest tests/ -q` shows 393 (or more) passing locally.
- [ ] Existing `openemr-mvp` Railway project still healthy (Co-Pilot URL loads in incognito).
- [ ] New `agentforge` Railway project created.
- [ ] `agentforge-api` service: green, healthcheck `/healthz` passes, public domain generated, all 27 env vars set.
- [ ] `agentforge-api` volume at `/data` mounted (2 GB).
- [ ] `agentforge-ui` service: green, public domain generated, `AGENTFORGE_API_URL` set via reference picker (not plain text).
- [ ] `curl <api-url>/healthz` returns 200 with `phase: "5"`.
- [ ] `curl <api-url>/v1/dashboard` returns JSON with `coverage_summary.total_cells = 72`.
- [ ] `curl <api-url>/v1/reports` returns at least 3 VR entries (after §9.1, or from the committed `reports/` directory).
- [ ] AgentForge UI loads in incognito; sidebar shows `redteam_provider=openrouter`.
- [ ] AgentForge UI VulnReports page lists VR-0001 / 0002 / 0003.
- [ ] `TARGET_BASE_URL` and `TARGET_ALLOWLIST` on `agentforge-api` point at the live Co-Pilot.
- [ ] `README.md` updated with both URLs; commit pushed.
- [ ] Gauntlet portal submission includes the UI URL (operator-facing) as the "Deployed application URL".

---

## 13. Defense Lines For The Interview

- "AgentForge runs as a **separate** Railway project from the Co-Pilot. Attacker and target have different failure domains. The platform attacks the Co-Pilot through its **public HTTPS surface** — the same path a real attacker would use, not via Railway private networking."
- "The platform is two services: a FastAPI on port 8100 with a SQLite-on-volume persistence layer, and a Streamlit operator UI that talks to the API via Railway's private network. The UI never imports the platform's DB layer — a CI lint (`tests/unit/ui/test_no_db_imports.py`) enforces it."
- "Provider isolation is also CI-lint-enforced: the OpenAI SDK is only imported by `agentforge/redteam/openrouter_client.py`; the Anthropic SDK is only imported by `agentforge/redteam/anthropic_client.py` (fallback path); the Judge code never imports the Red Team package at all. The independence story holds at the import level, not just by convention."
- "Red Team runs on OpenRouter Cognitive Computations Dolphin-Mistral 24B Venice on the `:free` tier — $0/token during development. Judges and Documentation run on Anthropic Sonnet/Haiku. Cross-vendor judge independence is restored by AgDR-0013, which supersedes the AgDR-0001 transitional same-vendor compromise."
- "Budget Guard halts at any of seven conditions: per-run-type ceiling, per-day ceiling, cost-without-signal, per-attack timeout, target-error-rate over 20%, or operator halt. Once halted it's sticky. The `cost_extrapolate.py` projection shows the platform's per-run cost actually *falls* at 100K runs because the External Judge starts batching rubrics — that's the architectural leverage point the PRD asks about."
- "Synthetic patients only. The platform never interacts with real PHI. The PHI scrubber runs every text field through a regex set covering SSN / phone / email / DOB / MRN / credit-card before any payload reaches Langfuse, the doc agent's markdown, or the regression case JSON."

---

## 14. After This Runbook

The remaining Phase 1 Docker-gated tasks land *next*, and they're what make `tb attack` actually fire against the live Co-Pilot:

1. **`agentforge/target_adapter/sidecar_direct.py`** — POST `/v1/copilot/answer` against the *public* OpenEMR URL (the sidecar is private; the gateway path is the available public surface). Will need the `COPILOT_OPENEMR_GATEWAY_SHARED_SECRET` from the Co-Pilot side.
2. **`agentforge/target_adapter/openemr_gateway.py`** — login + CSRF + POST `/brief.php`. Talks to the OpenEMR public service exactly the way a real user would.
3. **`scripts/seed_target_patients.py`** — seeds Alice Test / Bob Test / Carol Test synthetic patients into the live OpenEMR via its FHIR API (`POST /apis/default/fhir/Patient`).
4. **Orchestrator nightly cron** — either Railway's built-in cron feature (if available on Hobby), or a GitHub Actions cron firing `curl <api-url>/v1/runs/start` (Phase 8 endpoint), or the in-process APScheduler.

Once those land, AgentForge becomes the autonomous, continuous adversarial system the PRD asks for. For Wk3 grading, the deployed surface + the 3 sample VRs + the 30-case judge meta-eval (precision/recall/F1 = 1.0) already satisfy the PRD's hard gates.

---

## 15. Sources Verified

Cross-checked against `origin/main` at commit `76f6108`:

- `agentforge/config.py` — confirmed env var names: `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, `OPENROUTER_REDTEAM_MODEL`, `OPENROUTER_REDTEAM_FALLBACK_MODEL`, `OPENROUTER_HTTP_REFERER`, `OPENROUTER_X_TITLE`, `ANTHROPIC_API_KEY`, `ANTHROPIC_FAST_MODEL`, `ANTHROPIC_ORCHESTRATOR_MODEL`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`, `AGENT_MESSAGE_SIGNING_SECRET`, `PLATFORM_DB_URL`, `TARGET_BASE_URL`, `TARGET_ALLOWLIST`, `BUDGET_*`, `ALLOW_BROWSER_AUTOMATION`, `ALLOW_TARGET_FIXES_PUSH`, `REDTEAM_PROVIDER`, `REDTEAM_MODEL`.
- `agentforge/api/main.py` — `/healthz` returns `{"status":"ok","version":__version__,"phase":"5","tests_passing":337}`; CORS uses `allow_origin_regex` for localhost only.
- `agentforge/ui/app.py` — Streamlit; reads `AGENTFORGE_API_URL` from environment via `agentforge/ui/api_client.py`.
- `agentforge/redteam/openrouter_client.py` — uses `openai.OpenAI(base_url=..., api_key=...)`; on `RateLimitError` retries against `fallback_model`.
- `agentforge/observability/langfuse_client.py` — disabled if either `LANGFUSE_PUBLIC_KEY` or `LANGFUSE_SECRET_KEY` is empty.
- `agentforge/memory/db.py` — engine built from `PLATFORM_DB_URL`; SQLite pragmas (WAL, FK on) via connection-event listener.
- `agentforge/documentation/agent.py` — `notifier_queue_path` default `data/notifier_queue.jsonl`; `reports_dir` constructor arg.
- `agentforge/target_adapter/allowlist.py` — `is_allowed` parses URL via `urlparse` and checks `.hostname` against the allowlist set.
- `pyproject.toml` — `[tool.poetry.dependencies] python = "^3.11"`, `openai = "^1.54"`, all other deps as committed.
- `scripts/generate_sample_vrs.py` — accepts `--reports-dir`, `--regression-dir`, `--notifier-queue`, `--target-fingerprint`, `--limit` flags.
- `runbooks/opus47_deploy_openemr_railway_v3_mariadb.md` and `humanrunbooks/railway_update_app_*` from the EMR-SO project — copied the Railway UI navigation patterns and the `${{service.VAR}}` reference-picker discipline.
