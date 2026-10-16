# RydeResolve Demo Timing

## Target

- **Planned final duration:** 6:50
- **Maximum allowed:** 8:00
- **Exact spoken word count:** 754 words, including the scripted transition lines
- **Preferred delivery:** approximately 130 words per minute, with natural pauses
- **Editing buffer:** 1:10 below the maximum

## Speaking-time estimate

| Delivery rate | Spoken duration for 754 words | Practical use |
|---:|---:|---|
| 125 words/min | 6:02 | Slowest acceptable delivery; overlap clicks with speech and keep silent waits below 58 seconds. |
| 130 words/min | 5:48 | Recommended rehearsal pace; leaves about 62 seconds for visible progress, clicks, and holds. |
| 135 words/min | 5:35 | Comfortable fallback if live navigation takes longer. |
| 140 words/min | 5:23 | Upper limit; avoid going faster than this. |

The segment table assigns about 5:39 to spoken content and 1:11 to visual interaction. Most clicks and pointer movements occur during narration, while the remaining time covers visible ADP progress and the final hold. At approximately 130 words per minute, this produces the planned 6:50 edit.

## Segment budget

| Segment | Timestamp | Duration | Narration target | UI/loading allowance |
|---|---:|---:|---:|---:|
| Opening | 00:00–00:20 | 20 sec | 17 sec | 3 sec hold |
| Problem and value | 00:20–00:40 | 20 sec | 18 sec | 2 sec pointer movement |
| Three-agent solution | 00:40–01:00 | 20 sec | 19 sec | 1 sec |
| Implemented architecture | 01:00–01:20 | 20 sec | 19 sec | 1 sec |
| NS01 setup | 01:20–01:40 | 20 sec | 17 sec | 3 sec click |
| NS01 processing | 01:40–02:00 | 20 sec | 14 sec | 6 sec visible progress |
| NS01 result | 02:00–02:35 | 35 sec | 26 sec | 9 sec highlighting |
| NS01 evidence | 02:35–03:00 | 25 sec | 20 sec | 5 sec click and scroll |
| RT01 setup | 03:00–03:20 | 20 sec | 16 sec | 4 sec selection and click |
| RT01 processing | 03:20–03:35 | 15 sec | 11 sec | 4 sec visible progress |
| RT01 calculation | 03:35–04:15 | 40 sec | 31 sec | 9 sec highlighting and tab switch |
| DISP-001 setup | 04:15–04:35 | 20 sec | 16 sec | 4 sec selection and click |
| DISP-001 processing | 04:35–04:52 | 17 sec | 13 sec | 4 sec visible progress |
| DISP-001 ruling | 04:52–05:25 | 33 sec | 28 sec | 5 sec highlighting |
| Agent review | 05:25–05:45 | 20 sec | 17 sec | 3 sec click and expand |
| Technical differentiators | 05:45–06:05 | 20 sec | 18 sec | 2 sec tab changes |
| Development approach | 06:05–06:30 | 25 sec | 21 sec | 4 sec screen change |
| Impact and close | 06:30–06:50 | 20 sec | 18 sec | 2 sec final hold |
| **Total** | **00:00–06:50** | **410 sec** |  |  |

## Processing-time assumptions

The schedule includes approximately 15–20 seconds around each investigation, with narration continuing during most of that period. Actual ADP requests can take longer and may run until the configured timeout.

For a request that exceeds its segment:

1. Keep the initial click and visible progress.
2. Finish the processing narration.
3. Remove only the remaining silent wait in editing.
4. Resume when the completed recommendation appears.

With three 15-second silent overages removed, the final edited duration remains about 6:50. Without editing, three full 45-second requests could add roughly 90 seconds and bring the video near 8:20, so a clean loading-time edit may be necessary.

## Distinct contribution of each case

| Case | Primary capability | Decision shape | Why it is not repetitive |
|---|---|---|---|
| NS01 | GPS versus party claim | Full S$5 refund | Demonstrates objective location evidence in a no-show dispute. |
| RT01 | Route and monetary arithmetic | S$3.69 partial refund | Demonstrates proportional remedy calculation and refund capping. |
| DISP-001 | Conflicting evidence plus authority threshold | Human review; S$3.44 candidate remedy | Demonstrates driver mitigation, missing rider notification, organiser policy, and a mandatory stop to automation. |

## Judge-perspective quality check

### Does it answer the challenge?

Yes. The recording demonstrates an end-to-end dispute flow across no-show and route-deviation categories, with rider, driver, and Judge roles.

### Is multi-agent collaboration visible?

Partially and honestly. The role cards, Judge synthesis, and returned ADP activity metadata are visible. The script explicitly states that separate advocate reports are not returned as frontend outputs.

### Are the decisions policy-grounded?

Yes. NS01 and RT01 are clearly labelled as synthetic `demo-v1` decisions. DISP-001 cites the organiser Policy v2.1 autonomy threshold.

### Do the cases establish fairness?

Yes. NS01 protects the rider from a wrongly located pickup. RT01 limits compensation to supported excess fare. DISP-001 considers the driver’s valid traffic reason while still recognising the communication failure and human-review boundary.

### Is the technical implementation clear?

Yes. The script connects Streamlit, read-only evidence retrieval, Tencent ADP orchestration, structured output validation, deterministic calculations, citation checking, and human escalation to visible actions.

### Are limitations handled credibly?

Yes. The script does not claim production Ryde integration, calibrated confidence, executed payments, separate advocate transcripts, measured AI accuracy, or verified CodeBuddy history.

## Final timing check procedure

After one rehearsal:

1. Record the actual start and end time of each segment.
2. If the narration exceeds 6:50 before loading edits, remove pauses before increasing speaking speed.
3. Keep speech between 125 and 140 words per minute.
4. Preserve the two-second final hold.
5. Export only after confirming the final file is under 8:00.
