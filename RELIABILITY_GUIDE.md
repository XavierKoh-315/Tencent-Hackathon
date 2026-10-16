# Agent reliability update

This is a cumulative update for the original uploaded GPT(1).zip project. It includes the earlier human-review and dollar-sign display fixes. Back up the project, copy the supplied files into the existing project folder containing app.py, merge subfolders and choose Replace for matching supplied files. Keep your .env, .git, virtual environment and datasets.

## What changed

- The request to the published app explicitly asks for actual advocate report content, preservation of both reports, the configured handoff sequence, and a silent final consistency check. It does not transmit baseline expected answers to the model or replace its saved system prompts.
- A stream ending with an explicitly named Rider Advocate or Driver Advocate reply is rejected as the wrong final source. Unlabelled replies still need the existing Judge schema/citation/amount checks. An agent name is not evidence that both advocate reports were delivered.
- If the model itself requests human review, its actual explanation, proposed messages and confidence are preserved. RT01 now displays the reported missing-advocate reason and actual zero confidence rather than a generic baseline mismatch. The backend does not convert missing reports into a refund.
- A model-policy disagreement still goes to review. The supplied NS02 contradiction remains a pending review with zero awarded refund; the original 95% model score and original response remain available. The app never rewrites a contradictory refund into an assumed model no_action decision.
- The JSON report includes separate validation metadata and the untouched original model response, making it possible to distinguish a policy disagreement from model-requested review.
- The dollar-sign/bold text fix and previous human-review form remain included.

## Changes needed in ADP

Yes: add the text from each file below at the end of the matching agent's existing prompt. Do not replace the entire prompt. The additions explicitly supersede only conflicting instructions about report format, handoff, policy applicability and final consistency.

| File | Agent |
|---|---|
| agent_updates/JUDGE_APPEND.txt | Judge |
| agent_updates/RIDER_APPEND.txt | Rider Advocate |
| agent_updates/DRIVER_APPEND.txt | Driver Advocate |

The advocate report body is consistently position/statement/evidence_ids/policy_ids; the Judge keeps its required eight-field final JSON. Copy only the contents of the matching text file. Changing disputes/prompts.py in GitHub does not automatically edit the published ADP agents. Save and republish your application after making the ADP changes.

## Handoff settings

The screenshots supplied show the correct Free Handoff relationships already configured:

- Judge -> Rider Advocate and Driver Advocate
- Rider Advocate -> Judge
- Driver Advocate -> Judge

Keep these relationships. Their existence establishes allowed routing, not successful delivery of report text.

The Advanced Settings screenshot exposes "Hand over each new round of dialogue to" with "The Agent who replied to the user last" or "Main Agent". Select Main Agent with Judge configured as the main agent, then save both dialogs. This controls the next user turn; it does not map reports or guarantee context transfer. The current Streamlit implementation already creates a fresh ConversationId per investigation, so the selected last-speaker option does not by itself explain the supplied RT01 result.

No report-payload mapping is visible in the supplied settings. The prompt additions therefore instruct each advocate to include its completed public report through the actual supported handoff/context mechanism and instruct Judge to retain it. If the platform still does not deliver report content, a published-app trace is needed to diagnose that limitation. A prompt addition is not a guarantee of successful delivery. Switching to workflow orchestration is a separate architectural change and is not required by this code patch.

Use existing execution logs first. Check for each advocate's public report before its return to Judge, then check whether the Judge's context contains that actual report. Thought/tool activity alone is insufficient. No application access, handoff settings or published agents have been changed remotely on your behalf.

The title in your screenshots is Ride Dispute Review-copy01. Confirm this is the published application associated with the ADP_APP_KEY on your Streamlit Render service. Do not post the key. If a different app was edited, those changes will not reach the app your website calls.

## Local verification

Install dependencies and run:

    python -m pip install -r requirements.txt
    python -m unittest discover -s tests -v
    python verify_cases.py

151 local tests passed in the preparation environment on Streamlit 1.66.0, including replay of the two supplied original model outputs. All eight local policy baselines still match their expected outcomes. These are deterministic tests and controlled replies, not live model evaluations. The prompt additions and your ADP context configuration must still be verified against the published app. No paid requests were made.

## Push

Review `git status`, then stage only supplied files:

    git add app.py human_review_store.py disputes/core.py disputes/adp.py disputes/prompts.py requirements.txt README.md UPDATE_GUIDE.md VALIDATION.md RELIABILITY_GUIDE.md verify_cases.py tests/test_human_review_store.py tests/test_organiser_integration.py tests/test_app_workflow.py tests/test_review_regressions.py tests/test_agent_contract.py tests/fixtures/ns02_inconsistent.json tests/fixtures/rt01_missing_reports.json agent_updates validation/local_verification.json
    git commit -m "Preserve review reasons and strengthen agent report contracts"
    git push

Wait for the Render deployment to finish before checking https://ride-dispute-review.onrender.com/. Dependency installation and deployment use your existing Render configuration. The DATABASE_URL warning is separate: saving hosted human reviews still requires a reachable PostgreSQL database configured on the Streamlit service. Do not remove the storage check to hide the warning.

After the ADP changes are published, perform a minimal live check with a single selected case only if you have quota and want to spend tokens. NS02 should return consistent no_action/0 if both reports are available and the supplied demo evidence is unchanged. RT01 should return the supported partial refund only after both actual reports reach Judge; otherwise review must remain pending with the specific reason. Never weaken these conditions to match a demo answer.
