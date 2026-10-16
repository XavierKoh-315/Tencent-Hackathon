# Ride Dispute Review — hackathon starter

A runnable Python/Streamlit starter for the Ryde multi-agent dispute challenge.
The interface accepts a complaint and a synthetic trip ID, sends one request to a
published Tencent ADP multi-agent application, and validates the Judge's final
ruling against the demo policy and evidence IDs.

**Status:** The ADP multi-agent integration is the only user-facing review mode.
Offline evaluation utilities and tests are preserved separately for deterministic
baseline checks but are never exposed in the UI. An actual provider session
requires your published ADP application and local AppKey.
CodeBuddy/WorkBuddy usage proof must come from your own genuine development work.

## First milestone: open the local application

1. Install and sign in to Tencent's international CodeBuddy IDE:
   https://www.codebuddy.ai/
   Official installation guide:
   https://www.codebuddy.ai/docs/ide/Getting-Started/Installation
2. Extract this ZIP and open the **ryde_dispute_starter** folder in CodeBuddy.
   You should see `app.py` and `requirements.txt` directly in that folder.
3. Open CodeBuddy's terminal. These commands work in Windows Command Prompt or
   PowerShell without activating the environment:

```text
py --version
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Python 3.10 or newer is required. If the `py` launcher is unavailable but `python`
works and reports a supported version, use `python` for the first two commands.
If neither command works, install Python from https://www.python.org/downloads/windows/
and reopen the terminal.

4. Open the localhost URL shown in the terminal, normally http://localhost:8501.
5. Select **NS01**, enter the complaint, then click **Investigate dispute**.
   The app sends one request to the published ADP multi-agent application.
6. Select **RT01** and investigate to test a route-deviation case.

The first investigation also creates a local SQLite case log under `runtime/`.
Do not represent offline template arguments as real AI outputs.

## Use CodeBuddy for the next development step

Open **CODEBUDDY_START.md** and paste its first prompt into CodeBuddy's project chat.
The prompt asks CodeBuddy to inspect the starter and implement a useful evidence
timeline. Save genuine conversation screenshots during planning, implementation
and testing; keep the minimum three screenshots for submission.

This starter was prepared with ChatGPT assistance. Your development description
should accurately describe both that assistance and your own CodeBuddy work.
It does not contain fabricated CodeBuddy screenshots or claim to have used that tool.

## Second milestone: connect real ADP agents

1. Open the international ADP platform: https://adp.tencentcloud.com/
   Sign in or register using the organiser's ADP guide. An individual account can
   skip company information and card binding according to that supplied guide.
2. In **App Dev**, create a **Standard Mode** agent application. Name it
   `ride-dispute-prototype` or another name of your choice.
3. Choose a text model available in your account. Keep model configuration in ADP;
   the optional `ADP_MODEL_NAME` setting can stay blank.
4. Suggested base role instruction:

```text
You are a prototype ride dispute agent. Follow the current role instruction and
the supplied evidence. Return a single valid JSON object without markdown.
Use only supplied demo policies and evidence; identify missing facts explicitly.
```

5. Test a simple JSON answer in the ADP debug panel, then **publish** the app.
   Confirm it is running. Copy its **AppKey** from the published application's
   API/service-status area. Console labels may vary by release.
6. Copy `.env.example` to `.env` in the project folder. Fill in the AppKey locally:

```text
ADP_APP_KEY=your_actual_published_application_key
ADP_ENDPOINT=https://wss.lke.tencentcloud.com/adp/v2/chat
ADP_MODEL_NAME=
ADP_TIMEOUT_SECONDS=45
```

Keep the real key in your local `.env` or hosting secret settings. Do not paste it
into ChatGPT, a CodeBuddy conversation, screenshots or the GitHub repository.

7. In the running app, choose **ADP live AI**, select **NS01** and investigate.
   A successful investigation makes five model calls: two evidence-tool plans,
   two advocate case arguments and one judge recommendation. It uses three
   separate conversation contexts, with a fresh set for each investigation.
8. Check the visible evidence IDs, each advocate's case, the judge's policy
   references and the two party-facing messages. Do not infer success merely
   from an HTTP 200 response.

ADP's HTTP SSE reference:
https://www.tencentcloud.com/document/product/1254/81449
The adapter uses the published app's AppKey, per-call SystemRole and independent
ConversationId values. It reads reply messages and excludes thought/procedure text.
Credentials and provider error response bodies are not included in saved case logs.

ADP usage depends on your account's model allowance. Development-tool credits and
ADP runtime allowance are separate; check the console before repeated live evaluation.
No live provider requests were made when preparing this starter.

## Architecture

```mermaid
flowchart TD
    A["Complaint and trip ID"] --> B["Python coordinator"]
    B --> C["Rider Advocate"]
    B --> D["Driver Advocate"]
    C <--> E["Read-only evidence tools"]
    D <--> E
    C --> F["Judge"]
    D --> F
    E --> F
    F --> G["Policy validation"]
    G --> H["Recommendation and case log"]
```

- `app.py`: Streamlit interface (multi-agent mode only) and local result persistence.
- `disputes/core.py`: trip-scoped tools, coordinator, arithmetic and policy validator.
- `disputes/adp.py`: ADP API adapter, SSE response parsing and safe provider errors.
- `disputes/prompts.py`: legacy single-agent prompts (used only by `adp` mode in tests/evaluate).
- `data/cases.json`: 12 synthetic cases across both required categories.
- `data/policy.json`: explicitly invented demonstration policies, version `demo-v1`.
- `data/expected_results.json`: expected policy outcomes used only by evaluation/tests.
- `evaluate.py`: offline or legacy live comparison against the labelled synthetic scenarios.
- `tests/`: policy checks, monetary bounds, context isolation, SSE parsing and multi-agent validation.

Each advocate selects tools in live mode. Python executes the selected read-only
tools against the current trip. The judge receives both cases and the full retrieved
record. It chooses a recommendation; a separate validator checks the monetary and
policy result. A disagreement or low confidence produces human review.

## Tests and evaluation

Run the standard-library tests; these need no provider key:

```text
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe evaluate.py --mode offline
```

The offline mode checks the deterministic demo baseline only; it is never
exposed in the Streamlit UI. The app requires a published ADP multi-agent
application and a valid AppKey in `.env`.

Expected offline policy results: 12/12 labelled scenarios. This checks the
deterministic demo baseline, **not AI accuracy, production accuracy or business ROI**.
The route refund for RT01 is S$3.69: the synthetic GPS polyline excess is approximately
1.84266 km at 200 cents/km, rounded half up, below the 500-cent excess-fare cap.

Once configured, this command runs the 12 scenarios against actual ADP calls:

```text
.\.venv\Scripts\python.exe evaluate.py --mode adp
```

That makes up to 60 model calls and consumes provider allowance. Record the measured
outcome agreement and latency honestly; do not reuse the offline result as an AI score.

## Data and prototype limitations

- Everything in the sample dataset is synthetic. The policies are not Ryde's policies.
  Ask the organiser for the promised sample dataset and relevant actual policy rules,
  then update the evidence adapters and policy configuration consistently.
- Polyline distance is a GPS-data estimate. The reference route is supplied; the
  prototype does not find an optimal route on a road network or model traffic.
- Sparse pickup samples are assumed complete only for the declared synthetic cases.
  Production needs accuracy bounds, gaps, spoofing checks and continuous telemetry.
- Ratings, account age and past disputes alone do not decide guilt or refund eligibility.
- Confidence is a prototype heuristic/model self-assessment, not calibrated accuracy.
- Citation-ID checks validate references, not the semantic truth of every AI sentence.
- No real refunds are issued and no messages are transmitted to riders/drivers.
- This local single-user app is a hackathon prototype. Production authentication,
  per-user access control, secure hosted persistence and operational review processes
  remain future work.

## Two-day priorities

Day 1: open the offline app; use CodeBuddy for a real interface/data improvement;
configure ADP; run one live dispute from complaint to explained recommendation.

Day 2: verify both categories in live mode; improve evidence/policy citations; test
missing/contradictory records and review routing; measure live results; prepare the
architecture diagram, GitHub repository and demonstration.

## Submission checklist from the supplied Singapore handbook

Ryde challenge, pages 22–25:
- Three core agents using text and structured evidence.
- Working end-to-end flow for at least two categories.
- Visible agent communication, architecture diagram, demonstration walkthrough.
- Complete source code in a GitHub repository.

General submission rules, page 36:
- Original project built using at least CodeBuddy or WorkBuddy, with genuine proof.
- Minimum three development-conversation screenshots/screen recordings.
- Project title, short blurb strictly under ten words and project description.
- Description covers users/scenarios, solution design, prompts and business value.
- 16:9 cover image.
- Optional 5–8 minute demo video and optional live URL (the latter earns bonus points).

Submission deadline: 16 October 2026, according to the supplied handbook. Follow any
updated track instructions from the organiser. Keep actual credentials out of materials.

Sources used for requirements: the user-supplied **AI CAN DO IT Tencent Cloud AI
Singapore Hackathon 2026 Handbook.pdf**, **ADP_Hackathon_Guide_EN.pdf**, and official
ADP API / Streamlit documentation. This archive does not include or redistribute
the supplied handbook PDFs.

## Deployment on Render

The project deploys as two independent Python web services on Render.

### Prerequisites

- A published Tencent ADP multi-agent application and its AppKey.
- A Render account with two web services created (or to be created).

### Environment variables

| Variable | Required by | Purpose |
|---|---|---|
| `ADP_APP_KEY` | **Streamlit** only | Published ADP application key. Set in Render dashboard → Environment. |
| `ADP_ENDPOINT` | Streamlit (optional) | ADP SSE endpoint. Defaults to `https://wss.lke.tencentcloud.com/adp/v2/chat`. |
| `ADP_TIMEOUT_SECONDS` | Streamlit (optional) | Request timeout, 5–120. Defaults to 45. |
| `PORT` | Both (auto-set by Render) | Render sets this automatically. Do not set manually. |
| `DATABASE_URL` | Streamlit on Render | PostgreSQL connection string for durable human-review storage. Required for saving or loading reviews on Render; local development uses SQLite if unset. |

The Streamlit service reads `ADP_APP_KEY` from the server environment. A local `.env`
file is optional for development only and is never required in production.

### Build command (both services)

```text
pip install -r requirements.txt
```

### FastAPI evidence API

- **Root directory:** `ryde_dispute_starter` (where `api.py` lives)
- **Start command:**
  ```text
  uvicorn api:app --host 0.0.0.0 --port $PORT
  ```
- **Health check:** `GET /health` returns `{"status":"ok"}` with no credentials.
- No environment variables required beyond `PORT`.

### Streamlit app

- **Root directory:** `ryde_dispute_starter` (where `app.py` lives)
- **Start command:**
  ```text
  streamlit run app.py --server.address 0.0.0.0 --server.port $PORT --server.headless true
  ```
- Set `ADP_APP_KEY` in the Render dashboard Environment tab.

### Data file paths

All data files (`data/cases.json`, `data/policy.json`) load via `Path(__file__).resolve()`
relative to the Python source, not the working directory. This means the services work
correctly regardless of the working directory Render uses at startup.

### Security notes

- `.gitignore` excludes `.env`, `*.env`, and `runtime/` from Git.
- No API keys appear in UI, logs, or saved case results.
- The FastAPI `/health` endpoint exposes no credentials or sensitive details.
- The SQLite case log writes to `runtime/` which is ephemeral on Render and
  excluded from Git.

### Human-review record storage

Human-review records are stored separately from the AI result table and the
original AI result is preserved unchanged inside each review record.

| Variable | Required by | Purpose |
|---|---|---|
| `DATABASE_URL` | Streamlit on Render | PostgreSQL connection string for durable review storage. Local development uses `runtime/human_reviews.sqlite3` if unset. |

**Render setup for durable storage:**

1. Create a managed PostgreSQL database in the Render dashboard.
2. Copy the internal connection string (e.g. `postgresql://user:pass@host:5432/db`).
3. Set it as the `DATABASE_URL` environment variable on the Streamlit web service.
4. `psycopg2-binary` is in `requirements.txt` and will be installed automatically.

On Render, a missing/unavailable `DATABASE_URL` disables the review form and displays
an explanatory warning while keeping the AI recommendation visible. It never reports
a save as successful using temporary server storage. Locally, SQLite is used when
`DATABASE_URL` is unset. PostgreSQL must be reachable from the Streamlit service;
use an internal URL only when the database and service share the appropriate private network.

The decision selector updates outside the form, enabling the refund amount immediately.
Refund limits come from the saved payment evidence; unknown amounts are never zero.
Only a valid `human_review` result can be reviewed. A completed review becomes green,
with confidence shown as an em dash; further review stays amber and can be continued.
No payments or messages are executed.

Each record stores the untouched original AI result, case/run identifiers, policy,
reviewer-entered name, messages, explanation and UTC timestamp. Concurrent duplicate
submissions are serialized. Continuing a pending review appends a linked record;
previous records are never overwritten. The URL after saving includes the review's
random identifier so a refresh restores the same investigation without another ADP call.
These are demo records: the typed name and link are not an authentication system.

See `UPDATE_GUIDE.md` for replacement instructions and `VALIDATION.md` for local results.
`python verify_cases.py` checks all eight local baselines without ADP calls.
`python verify_cases.py --live --cases NS02` explicitly performs one paid ADP test
using your local `.env`; never upload the key or commit it.

## Organiser update kit integration

Three organiser-provided fixtures (DISP-001, DISP-002, DISP-003) are integrated
alongside the original 12 synthetic regression cases. The organiser cases use
**organiser policy v2.1**, which is loaded from `organiser_data/policy_v2_1.md`
and kept strictly separate from the synthetic demo policy.

### Case catalogue

| Case | Category | Policy | Baseline ruling | Notes |
|---|---|---|---|---|
| NS01–NS06 | no_show | demo-v1 | varies | Original regression suite |
| RT01–RT06 | route_deviation | demo-v1 | varies | Original regression suite |
| DISP-001 | route_deviation | organiser-v2.1 | human_review | 4.3 km excess > 2 km threshold |
| DISP-002 | no_show_charge | organiser-v2.1 | human_review | Fraud flag raises confidence threshold to 0.95 |
| DISP-003 | fare_dispute | organiser-v2.1 | refund S$4.50 | Surge diff, rider not notified |

### Policy isolation

- Organiser cases route through `organiser_support.get_evidence()` for all six tools.
- The `get_policy` endpoint returns organiser v2.1 clauses (prefixed `ORG-V2.1-*`)
  for DISP cases, and demo clauses (`DEMO-*`) for original cases.
- The validator accepts `ORG-V2.1-*` clause IDs for organiser cases and rejects
  `DEMO-*` IDs, and vice versa.

### DISP-001 policy conflict

DISP-001 has a 4.3 km route deviation exceeding the 2 km autonomous-resolution
threshold (policy 6.2). The excess-distance fare of S$3.44 is a candidate remedy
for the human reviewer — it is **not** automatically awarded. The baseline
escalates to `human_review` without hardcoding any sample answer.

### ADP tool output mapping

The ADP agents call six evidence tools. Each returns an `evidence_id` in the
format `{case_id}:{tool}`. The tool-to-data mapping for organiser cases:

| Tool | evidence_id | data key | Source |
|---|---|---|---|
| get_trip | `DISP-001:get_trip` | `trip` | `organiser_support.get_evidence()` |
| get_messages | `DISP-001:get_messages` | `messages` | `organiser_support.get_evidence()` |
| get_payment | `DISP-001:get_payment` | `payment` | `organiser_support.get_evidence()` |
| get_metrics | `DISP-001:get_metrics` | `metrics` | `organiser_support.calculate_metrics()` |
| get_policy | `DISP-001:get_policy` | `policy` | `organiser_data/policy_v2_1.md` |
| get_history | `DISP-001:get_history` | `history` | `organiser_support.get_evidence()` |

### ADP prompt addendum

Append the following to the Judge agent prompt so it returns the correct JSON
schema and cites organiser policy clauses for DISP cases:

```text
OUTPUT FORMAT — MANDATORY:
Return a single valid JSON object only. No prose, no markdown, no code fences.
The JSON must contain exactly these fields:

{
  "ruling": "refund" | "no_action" | "human_review",
  "refund_cents": <integer>,
  "confidence": <number 0.0–1.0>,
  "rationale": "<string>",
  "evidence_ids": ["<string>", ...],
  "policy_ids": ["<string>", ...],
  "rider_message": "<string>",
  "driver_message": "<string>"
}

Rules:
- ruling must be one of: "refund", "no_action", "human_review".
- refund_cents must be an integer. Use 0 for "no_action" or "human_review".
- confidence must be a finite number from 0 through 1.
- evidence_ids must cite IDs returned by the evidence tools (format: CASE_ID:tool).
- policy_ids must cite clause IDs from the get_policy response.
  For organiser cases these are prefixed "ORG-V2.1-" (e.g. "ORG-V2.1-6.2").
  For synthetic cases these are prefixed "DEMO-" (e.g. "DEMO-NOSHOW-01").
  Do not mix policy versions.
- All text must be in English.
- Output nothing except the JSON object.
```

### Test suite

```text
tests/test_core.py              — Original regression + validation tests
tests/test_adp.py               — SSE parser + ADP client tests
tests/test_api.py               — FastAPI endpoint + secret-exclusion tests
tests/test_organiser_support.py — Kit standalone tests (7 tests)
tests/test_organiser_integration.py — Full integration tests (28 tests)
```

Run all tests:
```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```
