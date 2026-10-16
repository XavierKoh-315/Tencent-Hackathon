# RydeResolve demo checklist and implementation audit

## What is actually implemented

| Area | Evidence in repository | Status for the video |
|---|---|---|
| Stack | `requirements.txt`, `app.py`, `api.py`, `disputes/adp.py` | Python 3.10+, Streamlit 1.66.0 UI, FastAPI/Pydantic evidence API, `urllib` HTTPS/SSE Tencent ADP adapter, local JSON fixtures, SQLite and optional PostgreSQL review storage. No JavaScript frontend or route based web pages. |
| Main UI | `app.py` | **Implemented** single Streamlit page: sidebar case selector and summary, editable prefilled complaint, Investigate button, status, recommendation, rationale, evidence metrics, three tabs, report download, and human review dialog for escalations. |
| Agent roles | `disputes/prompts.py`, `disputes/core.py`, `disputes/adp.py`, `agent_updates/` | **Configured externally / partially observable** in the user facing mode. One request goes to a published ADP multi agent app. Its Rider Advocate, Driver Advocate, Judge instructions and handoffs must already be saved and published there. The local source does not prove that the remote configuration is current. |
| Agent communication | `MULTI_AGENT_INSTRUCTIONS`, `ADPClient.review()`, `review_text()` | **Partially observable**. The outgoing request asks for Judge ↔ advocate handoffs and completed reports. The SSE parser returns the last reply as Judge JSON and captures activity metadata. Streamlit does not get separate structured advocate reports or show their exchange text. Event metadata alone is not proof of report delivery. |
| Evidence and metrics | `EvidenceTools` in `disputes/core.py`, `organiser_support.py`, `organiser_data/` | **Implemented** six read only, case scoped tools: `get_trip`, `get_messages`, `get_payment`, `get_metrics`, `get_policy`, `get_history`. Organiser cases use supplied road distance, waiting/contact counts, and surge data; evidence IDs take the form `CASE_ID:tool`. |
| Evidence API | `api.py` | **Implemented but separate**. `GET /health` and `POST /tools/get_trip`, `/get_messages`, `/get_payment`, `/get_metrics`, `/get_policy`, `/get_history`. Streamlit's current coordinator calls local evidence code directly; running this API is optional for the video. |
| Policy enforcement | `policy_decision()`, `_validate_multi_agent_ruling()`, `organiser_data/policy_v2_1.md`, `data/policy.json` | **Implemented, with limits**. Organiser cases use the supplied v2.1 policy; NS/RT cases use explicitly invented `demo-v1`. Python calculates a deterministic baseline; the final Judge JSON must have valid fields, existing citation IDs, and a bounded refund. Disagreement or low confidence escalates. Citation validation checks IDs, not whether every sentence is true. |
| End to end path | `app.py` → `resolve()` → `ADPClient.review()` → validator → UI | **Implemented if ADP is configured**. Complaint is sent to ADP, SSE final reply is parsed, checked, saved to `runtime/cases.sqlite3`, and displayed. A failed request shows diagnostics and accepts no decision. The app offers no offline button. |
| Review and communications | `app.py`, `human_review_store.py` | **Implemented as records/proposals**. Escalations can open a reviewer form and store a proposed decision locally in SQLite or in PostgreSQL when configured. A typed reviewer name is not authentication. No refund is paid and no rider/driver message is sent. |
| Data | `data/cases.json`, `organiser_data/DISP-00*.json` | Twelve original synthetic NS/RT cases plus three organiser supplied hackathon fixtures are loaded. The UI allowlist shows NS01–NS04, RT01–RT02, DISP-001, DISP-003. DISP-002 and six original cases are hidden from the selector. These are sample records, not verified production trips. |

### Important implementation limits to say accurately

- **DISP-001:** 4.3 km excess exceeds organiser policy 6.2's 2 km autonomous limit. The **S$3.44** excess distance charge is a **candidate** for a reviewer; the implemented baseline is **human review, S$0 pending**. The separate S$6.50 total fare difference includes other components.
- **DISP-002:** The supplied GPS/contact facts support the ordinary no show fee test: scheduled pickup to cancellation is 360 seconds, with four recorded driver messages and one call attempt. Its rider fraud flag is 1, so the implemented policy baseline escalates under clause 6.3. It is also hidden from the UI. Do not demonstrate it as “fee upheld.”
- **DISP-003:** The supplied quote is S$12.00, charge S$16.50, and surge differential S$4.50 with `rider_notified: false`. The implemented baseline proposes a **S$4.50 refund**. Live ADP output remains unverified here.
- **DISP-001 review form issue:** Organiser `get_payment` data nests `charged_cents` under `payment`; `charged_cents_for()` reads the outer object. The result is `None` for DISP-001, so a final human refund cannot be saved because the charge appears unknown. The dialog can still be shown and non refund decisions can be recorded. Do not claim that S$3.44 was saved as a final refund.
- **Confidence policy gap:** The current multi agent postcheck uses a flat 0.80 minimum for all organiser cases. Policy 6.1 says a fare dispute under S$10 can be final at any confidence, while 6.3 raises a fraud flagged case to 0.95. The deterministic DISP-002 baseline handles its fraud flag by escalation, but the generic postcheck does not itself implement each policy tier. Describe the implemented check, not a full policy engine.
- **Remote agents:** `disputes/prompts.py` includes a legacy local three call workflow and request instructions for the current mode. The current UI uses `mode="multi_agent"`, one ADP request. Changing local prompt files alone does not change published ADP agents. The presence of role cards and activity events does not prove successful handoff of advocate reports.
- **History and timing:** Case switching in one Streamlit session reuses a completed result. Refresh ordinarily loses unsaved session results; a saved human review link can restore its original AI snapshot. ADP latency and cost have not been measured in this checkout.

## Before the recording day

- [ ] Install dependencies in a private virtual environment; use the exact macOS commands in `demo-runbook.md`.
- [ ] Add the AppKey to a private `.env` or environment variable. Confirm it belongs to the **published** multi agent app you edited. Keep the key, `DATABASE_URL`, and ADP console secrets off screen.
- [ ] Confirm the remote Judge, Rider Advocate, and Driver Advocate have the current saved instructions/report formats and working handoffs. Look at genuine ADP execution traces if you will claim both advocate reports were delivered.
- [ ] Run the full local tests after installation: `python -m unittest discover -s tests -p 'test_*.py' -q`. Run `python verify_cases.py` for a local policy check. Never call that an AI accuracy measurement.
- [ ] Rehearse **DISP-003** and **DISP-001** through the actual UI once. Check visible status, citations, amounts, rationale, and both proposed messages. A real click consumes an ADP request.
- [ ] Check **DISP-003** returns a validated S$4.50 refund before using the positive result line. If it escalates, narrate the actual escalation instead.
- [ ] Check **DISP-001** returns human review. If the reason is missing advocate reports, state that actual reason and explain policy 6.2 separately.
- [ ] Confirm the human review dialog opens. Cancel without saving a final refund for DISP-001.
- [ ] Record at 16:9, readable browser zoom, sidebar open, quiet notification state. Keep terminal and `.env` hidden. Scroll enough to show values and clause IDs without lingering over raw JSON.
- [ ] Capture clean genuine screen footage of the ADP response and avoid editing together different runs as one investigation.

## What to do if something breaks

| Symptom | Likely cause / safe response |
|---|---|
| Missing AppKey or HTTP 401 | `.env` absent/incorrect, wrong published app, or unpublished ADP setup. Verify privately; no accepted result exists. |
| HTTP 429 | Provider quota/rate limit. Stop repeated clicks and use a later slot after checking allowance. |
| Timeout or incomplete SSE | Network/ADP issue. No partial ruling is accepted. Check the technical diagnostics and the remote execution trace. |
| Non JSON, missing citations, wrong amount, or advocate final reply | Published Judge/handoff/report contract needs attention. The app rejects invalid structured output; do not improvise a successful result. |
| Human review instead of expected refund | Read the actual reason. The validator intentionally escalates disagreement or low confidence. Show that as the live result if filming. |
| DISP-001 reviewer refund field cannot be completed | Known nested organiser payment shape described above. Show the review handoff only; do not save or claim a completed S$3.44 refund. |
| Hosted reviewer form says storage unavailable | `DATABASE_URL`/PostgreSQL is missing or unreachable on Render. Local SQLite works for development. Keep the AI result on screen; do not claim a review was saved. |
| Browser refresh loses a result | Return to the same running session if available or use the saved review link for a completed human review. A new investigation is another ADP call. |

## Development process reflection you can use

“I built this as a Python prototype around supplied dispute fixtures. I separated organiser policy from invented demo rules, added read only evidence tools and citation checks, then exercised policy, API, stream parsing and reviewer persistence with fixture based tests. I kept the model’s original response when a policy disagreement triggered review. I still need more live ADP evaluation and proper production authentication and payment integration.”

The repository includes `CODEBUDDY_START.md` and instructions to use CodeBuddy, plus `agent_updates/` text for remote prompts. It does **not** contain a verifiable CodeBuddy or WorkBuddy conversation, screenshot set, or commit history in this checkout. Add a first person CodeBuddy/WorkBuddy claim only if you have genuine records of that work and can show them. Do not use the repository's local test counts as provider model performance.

## Verification performed for this preparation

- Directly evaluated the local policy function: DISP-001 → `human_review/0`; DISP-002 → `human_review/0`; DISP-003 → `refund/450`; NS02 → `no_action/0`; RT01 → `refund/369`.
- Confirmed the visible case allowlist and the current one request ADP path from source.
- Confirmed the organiser review amount issue by passing a DISP-001 offline result into `charged_cents_for()`; it returned `None`.
- Ran 85 dependency free tests successfully across `test_core`, `test_organiser_support`, `test_human_review_store`, `test_adp`, and `test_review_regressions` (18 + 7 + 22 + 29 + 9).
- The full suite could not complete in this checkout because `streamlit` and `fastapi` are not installed. This checkout has no `.venv`, no `.env`, and no process `ADP_APP_KEY`; no real ADP request or live Streamlit walkthrough was performed. Prior `VALIDATION.md` documents 151 tests in another preparation environment, not a fresh full run here.
