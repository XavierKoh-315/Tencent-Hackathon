# Validation of this patch

Prepared from the uploaded GPT(1).zip. This is local verification, not certification of published ADP agents or organiser scoring.

## Results

- **151 automated tests passed** with Python 3.12 and Streamlit 1.66.0.
- All eight displayed cases matched the local policy baselines below.
- Streamlit started locally; both `/` and `/_stcore/health` returned HTTP 200.
- Streamlit AppTest rendered all eight result screens without application exceptions.
- Interaction checks covered immediate refund-field enablement, invalid amount retention, successful saving, immutable AI snapshots, confidence display, refresh recovery, case switching, storage failure, and a pending review followed by a final linked review.
- Storage checks covered finite decimal amounts, zero/unknown charges, correct case/run/policy binding, concurrent duplicate prevention and idempotent retries. SQLite was exercised; no live PostgreSQL instance was available for integration testing.
- ADP/parser/API regression tests passed using controlled fixtures. Missing citations are now rejected instead of being filled in by the backend. Original model JSON is preserved before a policy escalation.
- Streamlit is pinned to the tested version. An older 1.45 test environment had a dialog/AppTest re-entry failure; it is not the supported dependency for this patch.
- Pixel-by-pixel/browser screenshot comparison was not completed: local Chromium download failed, and the separate cloud browser could not reach the local server. UI behaviour was checked through Streamlit's testing runtime. Colour changes need a final visual check after deployment.
- No paid ADP requests were made, no key was supplied, and no Render deployment or database connection was changed.

## Eight displayed cases

Amounts below are proposed refunds, not issued payments. Baseline confidence is a prototype heuristic; it is not a live model score.

| Case | Type | Expected local outcome | Proposed refund | Reason |
|---|---|---|---:|---|
| NS01 | No-show charge | Refund | S$5.00 | Driver outside the agreed pickup radius |
| NS02 | No-show charge | No action | S$0.00 | Correct pickup point and sufficient verified waiting time |
| NS03 | No-show charge | Refund | S$5.00 | Driver cancelled before the required wait |
| NS04 | No-show charge | Human review | S$0.00 pending | Missing GPS prevents pickup verification |
| RT01 | Route deviation | Partial refund | S$3.69 | Supported excess fare from an unapproved detour |
| RT02 | Route deviation | No action | S$0.00 | Supplied record establishes an agreed or justified detour |
| DISP-001 | Route deviation | Human review | S$0.00 pending | 4.3 km deviation exceeds organiser policy 6.2's 2 km limit |
| DISP-003 | Fare dispute | Partial refund | S$4.50 | Supported surge differential without rider notification |

DISP-001's S$3.44 is a candidate remedy for a reviewer; it must not appear as an automated refund. Its organiser sample recommendation and the supplied escalation rule differ, so the policy-first baseline requires review.

## Limits

Real ADP outputs can differ from these baselines, and mismatches conservatively trigger human review. A matching local baseline does not prove the published Judge, advocates and remote tools are configured correctly. No actual ADP token count or latency was measured. The live verifier is explicitly opt-in; see UPDATE_GUIDE.md.

Synthetic NS/RT policies and organiser-provided hackathon reference policies remain separate. This patch does not edit those policy files, prompts or datasets. Cases hidden from the dropdown remain in the original regression datasets.

## Reliability follow-up

The original NS02 and RT01 model outputs supplied by the user are replayed as local fixtures. Tests verify that NS02's contradictory refund remains escalated, RT01's missing-report explanation and zero model confidence remain intact, consistent controlled outcomes are accepted, and explicitly labelled advocate final replies are rejected. The outgoing request contains no expected-case answers. These checks do not prove the published ADP prompts or context settings were updated. See RELIABILITY_GUIDE.md.
