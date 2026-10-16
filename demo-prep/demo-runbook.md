# RydeResolve recording runbook

## 1. Launch locally (macOS / zsh)

From `/Users/zhihong/Documents/Tencent-Hackathon-main`:

```zsh
python3 --version                 # Python 3.10+
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` privately to set `ADP_APP_KEY` for the **published multi agent ADP application**. Leave `ADP_ENDPOINT` at the supplied HTTPS endpoint unless your account uses a supported alternative. `ADP_TIMEOUT_SECONDS=45` is the default; the code accepts 5–120. An environment variable overrides the `.env` value. Hide the key and browser console before recording.

```zsh
python -m unittest discover -s tests -p 'test_*.py' -q
python verify_cases.py
python -m streamlit run app.py
```

Open `http://localhost:8501`. The eight visible fixtures are loaded automatically from `data/cases.json` and `organiser_data/`; there is no import button or separate seed step. `verify_cases.py` is **local policy only** and writes `runtime/local_verification.json`; it makes no ADP calls. Pressing **Investigate dispute** is a real ADP request and can consume provider allowance. You do **not** need to run `api.py` for the Streamlit demo: `disputes/core.py` reads local evidence directly. The optional read only FastAPI service can be started separately with `python -m uvicorn api:app --port 8000`; it exposes `GET /health` and six `POST /tools/get_*` routes, but this UI does not call it over HTTP.

## 2. One complete dress rehearsal before recording

1. Confirm the published ADP app associated with `ADP_APP_KEY` has the Rider Advocate, Driver Advocate, and Judge roles, working handoffs, and the saved report formats described in `agent_updates/`. Local prompt text in `disputes/prompts.py` does **not** update published ADP agent settings.
2. Open Streamlit. Confirm the sidebar has **DISP-003** and **DISP-001**; **DISP-002** is deliberately not visible. Confirm both selected complaints are prefilled.
3. Run **DISP-003** once. Continue with the planned refund narration only if a valid result appears with `refund`, **S$4.50**, organiser policy citations, and sensible party messages. Inspect **Agent review → Investigation activity** for actual metadata. Activity alone does not establish that both full advocate reports reached the Judge; verify that in the ADP console if you plan to claim it.
4. Run **DISP-001** once. Continue with the planned escalation narration only if a valid result appears as **Human review required**. Verify the displayed rationale, and use **Evidence & policy** for the 4,300 metre / 344 cent figures. If the Judge’s reason is only “missing advocate report,” describe that as the live reason; you can still explain the separate policy threshold from the metrics and policy data.
5. If a run fails or differs, diagnose before recording. Do not repeatedly click to chase the expected answer. Each click creates a new ADP investigation. In the same Streamlit session, switching back to a completed case restores its cached result without another call. Refreshing normally loses unsaved session results.
6. Check the visual layout at the recording resolution. The source documents report AppTest checks, but no final pixel by pixel browser comparison. Confirm that amount formatting, cards, dialog, and scrolling look right on your machine.

## 3. Click by click recording sequence

1. Start on `http://localhost:8501`, at the page title **Ride Dispute Review**, sidebar open. Keep secrets and terminal windows out of view.
2. Sidebar **Select a case** → **DISP-003 — Fare Dispute**. Read the prefilled complaint. Point out charged **S$16.50** and reference **S$12.00**.
3. Click **⚡ Investigate dispute** once. Capture the investigating state and completion. If the request takes longer than the allotted scene, remove only idle footage in the edit.
4. Capture the recommendation card and **Why this outcome?**. The planned line requires the actual validated result to be **Refund recommended / S$4.50**.
5. Click **Evidence & policy**. Scroll to the JSON metrics (`fare_difference_cents: 450`, `surge_difference_cents: 450`). Open **DISP-003:get_payment** or **DISP-003:get_metrics** if the compact metric block is too small. Show the **Policy (organiser-v2.1)** heading.
6. Click **Agent review**. Show Rider Advocate, Driver Advocate, Judge, and the on screen caveat about absent separate advocate reports. Expand **Investigation activity** briefly. Close it.
7. Click **Proposed party messages**. Show rider and driver drafts and the no message sent note.
8. Sidebar **Select a case** → **DISP-001 — Route Deviation**. Read the prefilled complaint.
9. Click **⚡ Investigate dispute** once. Capture the result. The planned escalation line requires the actual validated result to be **Human review required / Pending human review**.
10. Click **Evidence & policy**. In metrics, show `excess_distance_m: 4300.0` and `excess_distance_fare_cents: 344`. If useful, expand **DISP-001:get_policy** and show clause `ORG-V2.1-6.2`; avoid a long JSON scroll.
11. Scroll back to the resolution card. Click **📝 Review case**. Show the **Human review — demonstration workflow** dialog, then **Cancel**. Do not save a final refund for DISP-001: this version reads the organiser charge as unknown in the review form.
12. End with the case ID, review outcome, and organiser policy version on screen. Record the closing line in `demo-script.md`.

## 4. If the live result is different

| What appears | Honest on camera wording and action |
|---|---|
| ADP authentication, quota, timeout, incomplete stream, or JSON/schema error | Stop that live take. Check `.env`, published status, quota and ADP trace privately. The UI accepts no decision in these cases. Do not cut in a local policy baseline as if it were the model result. |
| DISP-003 becomes human review | Say: “This run went to human review. The underlying fixture supports a S$4.50 surge differential, but this run did not approve it.” Then read the actual escalation reason; it may be a model request, policy disagreement, or low confidence. |
| DISP-001 becomes human review because an advocate report is missing | Say: “This live run says a report was unavailable to the Judge. Separately, the supplied policy also requires review for a 4.3 km deviation.” Do not claim the handoff completed. |
| The response contradicts a policy baseline | Show **Human review required** and, if appropriate, the saved `original_ai_ruling` in the report or **Original AI review** after a saved review. Explain that the validator preserves the original response and escalates. |
| The model explicitly requests review | The app preserves its stated reason and confidence. Read that reason; do not substitute the deterministic baseline’s explanation. |
| You lack a working ADP key | A live multi agent UI demo is unavailable. The offline policy function and tests can be shown **clearly labelled as local simulation**, but the Streamlit Investigate button has no offline mode. |

## 5. Architecture in 30 seconds

```text
Streamlit single page (app.py)
  → Python coordinator (disputes/core.py)
      → six read only, case scoped evidence tools (local JSON + organiser_support.py)
      → policy baseline and calculated metrics
  → one HTTPS/SSE request (disputes/adp.py)
      → published Tencent ADP application: Rider Advocate ↔ Judge ↔ Driver Advocate
  → Judge JSON → schema/citation/amount/policy checks
  → recommendation, evidence tabs, activity metadata, proposed messages
  → optional human review record (local SQLite; PostgreSQL when configured)
```

The frontend does not orchestrate three separate model calls in its current mode. It sends **one** request to the published ADP multi agent app with a fresh conversation ID. Handoffs and report exchange occur inside that remote configuration. Python receives the final reply plus stream activity metadata; `result["advocates"]` is empty in this mode. The separate FastAPI service is available for evidence endpoints but is not in the Streamlit call path. Local case results are logged in `runtime/cases.sqlite3`; local human reviews go to `runtime/human_reviews.sqlite3`. On Render, human review persistence requires `DATABASE_URL` for PostgreSQL. Neither flow issues a payment or sends a message.

## 6. Scenario choice

| Case | In organiser data | In Streamlit selector | Local policy baseline | Recording choice |
|---|---:|---:|---|---|
| **DISP-003**, fare dispute | Yes | Yes | Proposed **S$4.50** refund | **First**: clearest positive resolution, easy fare arithmetic and policy citations. |
| **DISP-001**, route deviation | Yes | Yes | **Human review**, S$0 pending; **S$3.44** is a reviewer candidate | **Second**: demonstrates policy guardrail and human oversight. |
| **DISP-002**, no show charge | Yes | **No** | **Human review**, S$0 pending, due to fraud flag confidence rule | **Do not present as a UI fee upheld case.** The recorded contacts and wait support retaining the fee on ordinary facts, but the implemented baseline escalates. |

If a third case is needed after a successful rehearsal, **NS02** is visible and has a local demo policy baseline of charge retained. Label it as a separate synthetic demo case. An earlier controlled model output for NS02 contradicted that baseline, so verify the live result before adding it to the video.
