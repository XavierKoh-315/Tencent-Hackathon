# RydeResolve Recording Runbook

## 1. Local setup

Run from:

```text
/Users/zhihong/Documents/Tencent-Hackathon-main
```

### Required private environment

Create `.env` locally from `.env.example` if it does not already exist. Never show or commit the real key.

```text
ADP_APP_KEY=your_published_application_key
ADP_ENDPOINT=https://wss.lke.tencentcloud.com/adp/v2/chat
ADP_TIMEOUT_SECONDS=45
```

`ADP_MODEL_NAME` may remain blank. `DATABASE_URL` is unnecessary for this recording because the runbook does not save a human review.

### Install and verify

```bash
cd /Users/zhihong/Documents/Tencent-Hackathon-main
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python verify_cases.py
./.venv/bin/python -m unittest discover -s tests -v
```

`verify_cases.py` checks local policy baselines and uses no ADP tokens unless `--live` is explicitly supplied.

### Start the application

```bash
cd /Users/zhihong/Documents/Tencent-Hackathon-main
./.venv/bin/python -m streamlit run app.py --server.port 8502
```

Open [http://127.0.0.1:8502/](http://127.0.0.1:8502/).

## 2. Recording preparation

1. Use a 16:9 recording canvas at 1920×1080 if available.
2. Set browser zoom so the sidebar, complaint, button, and result cards fit comfortably. Start around 90% or 100%.
3. Close unrelated tabs, notifications, terminals containing environment variables, and password-manager popups.
4. Keep the mouse pointer visible.
5. Turn on Do Not Disturb.
6. Confirm the page text has strong contrast and no browser-level forced colour mode.
7. Keep `final-demo-script.md` on a second display or printed copy.
8. Do one private preflight of all three cases before recording. This spends three live ADP requests.
9. Start the final recording in a fresh browser session so the Investigate button and progress state are visible.

## 3. Preflight acceptance checks

### NS01

Expected display:

- **Refund recommended**
- **S$5.00** proposed refund
- `demo-v1`
- Maximum pickup distance approximately **333.6 m**
- Verified wait **6.0 min**
- Policy `DEMO-NOSHOW-01`

Reject the take if the case fails schema validation or the live answer becomes human review. Investigate the published ADP prompt or handoff before recording; do not narrate a refund over a different screen.

### RT01

Expected display:

- **Refund recommended**
- **S$3.69** proposed refund
- Actual route approximately **6.29 km**
- Reference route approximately **4.45 km**
- Deviation approximately **141.4%**
- `calculated_refund_cents: 369`
- Policy `DEMO-ROUTE-01`

Reject the take if the model says required advocate reports are missing or if the validator escalates it. Do not describe the coordinates as a rendered map; the current UI shows metrics, a timeline, and evidence records.

### DISP-001

Expected display:

- **Human review required**
- Refund decision **Pending human review**
- Actual route **24.80 km**
- Reference route **20.50 km**
- Deviation **121.0%**
- Explanation references a **4.3 km** excess and a **S$3.44 candidate remedy**
- Organiser clause `ORG-V2.1-6.2`

Do not require an exact confidence number; it depends on the accepted live Judge response. Do not click **Review case** during the demo.

## 4. Exact recording sequence

### Opening and architecture

1. Load the application at NS01.
2. Confirm the status reads **Ready to investigate**.
3. Show the sidebar summary and complaint card.
4. Explain the three roles and the Python/Streamlit, FastAPI, and Tencent ADP architecture.

### Case 1 — NS01

1. Select **NS01 — Driver at the wrong pickup point** if needed.
2. Leave the supplied complaint unchanged.
3. Click **⚡ Investigate dispute** once.
4. During the wait, show the evidence retrieval progress.
5. On completion, show the resolution card and evidence-at-a-glance card.
6. Click **Evidence & policy**.
7. Show Python-calculated metrics.
8. Scroll to the evidence timeline.
9. Briefly show the `demo-v1` policy warning and `DEMO-NOSHOW-01`.

### Case 2 — RT01

1. Select **RT01 — Unapproved detour with excess fare** in the sidebar.
2. Leave the complaint unchanged.
3. Click **⚡ Investigate dispute** once.
4. Show the S$3.69 recommendation.
5. Point to the actual route, reference route, and deviation percentage.
6. Click **Evidence & policy**.
7. Show `calculated_refund_cents: 369` in the metrics.

### Case 3 — DISP-001

1. Select **DISP-001 — Route Deviation**.
2. Show **Dataset: Organiser-provided**.
3. Leave the complaint unchanged.
4. Click **⚡ Investigate dispute** once.
5. Show **Human review required** and **Pending human review**.
6. Point to the 24.80 km actual route, 20.50 km reference route, and 121.0% deviation.
7. Show **Why this outcome?** and explain the 4.3 km policy limit breach.
8. Do not click **Review case**.
9. Click **Agent review**.
10. Point to the three role cards.
11. Expand **Investigation activity** and show the metadata actually returned.
12. Collapse it.
13. Click **Evidence & policy** and show the organiser policy citations.
14. Click **Proposed party messages** and show both messages.
15. Return to the DISP-001 resolution card for the conclusion.

## 5. Loading and editing plan

- Budget roughly 15 seconds for each ADP request in the target timeline.
- The configured timeout can be as high as 45 seconds, so actual processing may vary.
- Continue the scripted processing narration while the first 15–20 seconds run.
- If a spinner remains after the narration, make a clean edit that removes only the idle wait.
- Do not cut directly from “Ready to investigate” to a result. Keep the click and at least several seconds of genuine progress visible.
- Never click Investigate twice. A second click can consume another request or replace the current run.

## 6. Failure guide

| Symptom | Meaning | Recording response |
|---|---|---|
| ADP authentication failed | Key missing, invalid, or unpublished application | Stop. Correct `.env` privately and restart Streamlit. |
| Quota or rate-limit error | Provider allowance unavailable | Stop repeated attempts. Check Tencent ADP allowance. |
| Request timeout | No completed response was accepted | Check ADP health; raise timeout only within the supported 5–120 second range. |
| Stream ended before completion | Incomplete SSE response | Retry once after checking provider status; do not present a partial ruling. |
| Schema validation failed | Judge output lacked required structured fields or valid citations | Fix the published Judge instruction; do not hide the diagnostic. |
| NS01 or RT01 becomes human review | Live answer disagreed with the local policy baseline, confidence was low, or required reports were unavailable | Do not use the prepared refund narration. Repair and preflight again. |
| DISP-001 returns a refund from the model | The Python policy validator should convert the displayed outcome to human review | Narrate the displayed human-review result and the policy boundary. |
| No activity entries appear | ADP returned no readable activity metadata | Keep the expander closed and omit any claim that a trace is visible. The final ruling can still display. |
| Human-review storage warning | `DATABASE_URL` is unavailable | Ignore for this demo because no reviewer decision is saved. Do not open the review form. |

## 7. Presenter accuracy guardrails

- NS01 and RT01 use synthetic data and invented `demo-v1` policies.
- DISP-001 uses the organiser-provided hackathon Policy v2.1 reference, which is not verified production Ryde policy.
- The application provides recommendations only.
- No refund is paid and no party message is sent.
- Confidence is uncalibrated.
- The three role cards are descriptive. The frontend does not receive separate structured advocate reports.
- The current live path sends one request to the published ADP application; ADP manages the internal roles.
- Local test success is not live-model accuracy.
- The repository contains CodeBuddy preparation material but no independently verifiable evidence that CodeBuddy or WorkBuddy was actually used. Keep it out of the spoken development history unless genuine external evidence is available.

## 8. Final thirty-second checklist

- [ ] Correct browser and localhost URL visible
- [ ] NS01 selected and status ready
- [ ] Microphone level tested
- [ ] Notifications disabled
- [ ] No credentials or `.env` visible
- [ ] ADP quota available
- [ ] NS01 preflight passed
- [ ] RT01 preflight passed
- [ ] DISP-001 preflight passed
- [ ] Script and runbook within reach
- [ ] Recording indicator active
