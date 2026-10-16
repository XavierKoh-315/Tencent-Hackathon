# RydeResolve Final Demo Script

**Target duration:** 6:50

**Cases:** NS01 → RT01 → DISP-001

**Recording format:** Product demonstration with spoken narration
**Important:** Use a preflighted browser session and follow the expected-result checks in `recording-runbook.md`. The amounts below are recommendations; the application does not execute refunds or send messages.

## 00:00–00:20 — Opening

**ON SCREEN:**

- Show the full RydeResolve application at the top of NS01.
- Keep the sidebar, “Ride Dispute Review” heading, and “Ready to investigate” badge visible.
- Do not move the pointer for the first sentence.

**NARRATION:**

“A ride dispute begins with two different stories and evidence to check. RydeResolve is our multi-agent resolution prototype for the Tencent Cloud AI CAN DO IT Hackathon, in the Digital Native — Ryde track.”

**KEY POINT:** The product directly addresses the ride-hailing dispute challenge.

**TRANSITION:** “Here is the problem.”

## 00:20–00:40 — Problem and value

**ON SCREEN:**

- Slowly move the pointer over the complaint card, case queue, and status badge.
- Keep the page at its initial position.

**NARRATION:**

“Manual reviews require an operator to compare claims, GPS, messages, payments, and policy. Our goal is to organise that evidence, represent both parties fairly, and produce a consistent, policy-grounded recommendation with human oversight.”

**KEY POINT:** RydeResolve targets speed, consistency, transparency, and fairness without claiming measured production gains.

**TRANSITION:** “We use three roles.”

## 00:40–01:00 — Three-agent solution

**ON SCREEN:**

- Point to the subtitle: “Three specialised AI agents. Every perspective considered.”
- Keep NS01 selected. Do not investigate yet.

**NARRATION:**

“The Rider Advocate builds the rider’s evidence-based position. The Driver Advocate looks for operational context. The Judge weighs both sides and returns a structured ruling with citations. These roles reduce the risk of accepting one party’s account as the answer.”

**KEY POINT:** Multiple roles create an adversarial review before judgment.

**TRANSITION:** “The application checks that judgment.”

## 01:00–01:20 — Implemented architecture

**ON SCREEN:**

- Point briefly to the case selector and complaint field.
- Position the pointer over **Investigate dispute**.

**NARRATION:**

“The interface uses Python and Streamlit. A read-only FastAPI service exposes case-scoped evidence, while Tencent ADP manages the agent workflow. Python then schema-checks the final JSON, bounds any refund against the charge, and compares it with policy logic.”

**KEY POINT:** This combines live agent reasoning with deterministic safeguards.

**TRANSITION:** “First, a no-show dispute.”

## 01:20–01:40 — Case 1: NS01 setup

**ON SCREEN:**

1. Confirm **NS01 — Driver at the wrong pickup point** is selected.
2. Point to the S$5 cancellation fee in the sidebar.
3. Point to the rider’s complaint.
4. Click **⚡ Investigate dispute** once.

**NARRATION:**

“In NS01, the rider says the driver never reached the pickup point but charged a five-dollar cancellation fee. The vehicle’s recorded position is decisive, so I’ll submit the unchanged complaint.”

**KEY POINT:** The first case has a simple claim and a decisive objective test.

**TRANSITION:** “The investigation now runs.”

## 01:40–02:00 — NS01 processing

**ON SCREEN:**

- Leave the expanded progress status visible.
- Point to retrieved evidence IDs as they appear.
- If the result finishes early, move to the recommendation card but wait for the narration before scrolling.

**NARRATION:**

“The backend gathers trip, message, payment, metric, policy, and history records. ADP manages the advocate and Judge roles, and the ruling must cite recognised evidence and policy identifiers.”

**KEY POINT:** Evidence is case-scoped and citations are validated.

**TRANSITION:** “Now, the result.”

## 02:00–02:35 — NS01 result

**ON SCREEN:**

1. Show the green **Resolution recommendation** card.
2. Point to **Refund recommended**, **S$5.00**, and the confidence field.
3. Point to **Evidence at a glance**: 333.6 m and 6.0 min.
4. Do not claim that the confidence is calibrated accuracy.

**NARRATION:**

“RydeResolve recommends a full five-dollar refund. The driver waited six minutes, but GPS places the vehicle about three hundred and thirty-three metres from the pickup point. The prototype policy allows a one-hundred-metre radius, so waiting at the wrong location does not justify the charge.”

**KEY POINT:** GPS resolves a direct contradiction between the driver’s claim and recorded location.

**TRANSITION:** “Here is the evidence trail.”

## 02:35–03:00 — NS01 evidence trail

**ON SCREEN:**

1. Click **Evidence & policy**.
2. In **Python-calculated metrics**, point specifically to `max_pickup_distance_m: 333.6` and `verified_wait_seconds: 360`.
3. Scroll through **Evidence timeline (Asia/Singapore time)**. Pause on the driver’s “I am at the pickup point” claim, the GPS observations, the rider’s “I cannot see your car” claim, and the cancellation event.
4. Point to the collapsed **Evidence records** list to show that the trip, messages, payment, metrics, policy, and history remain auditable. Do not open every record.
5. Briefly show the `DEMO-NOSHOW-01` policy section and its synthetic-policy warning.
6. Keep **Download case report (JSON)** collapsed; do not discuss it.

**NARRATION:**

“The timeline separates claims from telemetry in Singapore time, while the source records remain available below for audit. Python performs the calculations and the Judge explains the result. The policy is clearly labelled synthetic, rather than production Ryde policy.”

**KEY POINT:** The product distinguishes claims, observations, calculations, and policy provenance.

**TRANSITION:** “Next is a proportional remedy.”

## 03:00–03:20 — Case 2: RT01 setup

**ON SCREEN:**

1. In the sidebar, select **RT01 — Unapproved detour with excess fare**.
2. Let the page return to the top automatically; scroll to the top if needed.
3. Point to the complaint.
4. Click **⚡ Investigate dispute** once.

**NARRATION:**

“RT01 is a route-deviation dispute. The rider says the driver took a longer route without permission and charged above the reference fare. This time, the system must calculate a supported partial refund.”

**KEY POINT:** RT01 adds route comparison and monetary calculation.

**TRANSITION:** “The same pipeline evaluates it.”

## 03:20–03:35 — RT01 processing

**ON SCREEN:**

- Keep the progress status visible.
- If processing exceeds 15 seconds, pause the recording at the spinner and resume when the recommendation appears.

**NARRATION:**

“The agents receive the route, messages, payment record, and policy identifiers. The amount must still pass local payment and policy checks.”

**KEY POINT:** The same guarded pipeline works across dispute categories.

**TRANSITION:** “The excess distance sets the remedy.”

## 03:35–04:15 — RT01 calculation

**ON SCREEN:**

1. Show **Refund recommended** and **S$3.69**.
2. Point to **Actual route: 6.29 km**, **Reference route: 4.45 km**, and **Deviation: 141.4%**.
3. Click **Evidence & policy**.
4. Keep **Python-calculated metrics** visible, including `calculated_refund_cents: 369`.

**NARRATION:**

“The actual route is 6.29 kilometres against a 4.45-kilometre reference: about 1.84 kilometres extra. The detour was neither approved nor justified. Under the synthetic route policy, Python applies two dollars per excess kilometre, rounds to cents, and caps the amount against supported excess fare. The result is a S$3.69 partial refund.”

**KEY POINT:** The refund is reproducible arithmetic, not an amount invented by the model.

**TRANSITION:** “Finally, automation meets its limit.”

## 04:15–04:35 — Case 3: DISP-001 setup

**ON SCREEN:**

1. Select **DISP-001 — Route Deviation**.
2. Point to **Dataset: Organiser-provided** in the sidebar.
3. Point to the Orchard Central to Changi Airport T3 complaint.
4. Click **⚡ Investigate dispute** once.

**NARRATION:**

“DISP-001 is organiser-provided. The trip was 24.8 kilometres instead of 20.5, and the fare rose from S$28.50 to S$35. The rider says no traffic reason was communicated.”

**KEY POINT:** This case uses richer organiser evidence and Policy v2.1.

**TRANSITION:** “The evidence supports both sides.”

## 04:35–04:52 — DISP-001 processing

**ON SCREEN:**

- Leave the progress status visible.
- If processing exceeds 17 seconds, pause at the spinner and resume on the result.

**NARRATION:**

“Traffic records support rerouting around a vehicle fire and congestion. The messages do not show a clear explanation to the rider. This is where competing advocates matter.”

**KEY POINT:** Driver justification and rider-notification failure coexist.

**TRANSITION:** “The Judge applies the autonomy limit.”

## 04:52–05:25 — DISP-001 ruling

**ON SCREEN:**

1. Show the red **Human review required** card.
2. Point to **Pending human review** and the organiser policy version.
3. Point to **Evidence at a glance**: 24.80 km, 20.50 km, and 121.0%.
4. Show **Why this outcome?**
5. Do not click **Review case**.

**NARRATION:**

“The excess-distance fare is S$3.44, and missing notification supports it as a candidate remedy. But the deviation is 4.3 kilometres. Organiser Policy v2.1 permits autonomous route decisions only up to two kilometres. RydeResolve therefore requires human review and executes no refund. It considers the traffic reason without exceeding its authority.”

**KEY POINT:** Policy controls whether the AI may decide, even when it can calculate a remedy.

**TRANSITION:** “Now, the visible agent workflow.”

## 05:25–05:45 — Agent review and activity

**ON SCREEN:**

1. Click **Agent review**.
2. Point across **Rider Advocate**, **Driver Advocate**, and **Judge**. Pause briefly on the Judge’s final synthesis, but do not read the whole paragraph aloud.
3. Expand **Investigation activity**.
4. Scroll only enough to show activity entries that were actually returned.

**NARRATION:**

“Agent Review identifies the three roles, shows the Judge’s synthesis, and exposes readable ADP activity metadata when returned. The interface states that separate advocate reports are not structured frontend outputs, so these cards are not presented as transcripts.”

**KEY POINT:** The demo accurately distinguishes real orchestration metadata from static role descriptions.

**TRANSITION:** “Safeguards surround that response.”

## 05:45–06:05 — Technical differentiators

**ON SCREEN:**

1. Collapse **Investigation activity**.
2. Click **Evidence & policy** and show the cited organiser clauses.
3. Click **Proposed party messages** and show the rider and driver columns side by side. Do not read either message in full.
4. Leave **Download case report (JSON)** collapsed.

**NARRATION:**

“Every ruling needs structured fields, recognised evidence and policy IDs, and a refund within the charge. Policy mismatches or low confidence become human review. The system drafts separate party messages, but sends nothing and executes no payment.”

**KEY POINT:** Validation, escalation, and party-specific explanations make the recommendation safer and auditable.

**TRANSITION:** “Validation was our main challenge.”

## 06:05–06:30 — Development approach

**ON SCREEN:**

- Keep the two proposed messages visible, then return to **Agent review** near the end.

**NARRATION:**

“The challenge was accepting useful model reasoning without trusting arbitrary output. We added schema validation, citation checks, monetary bounds, policy comparison, and controlled regression fixtures. Local baseline tests remain separate from live ADP behaviour, so test success is not presented as measured AI accuracy.”

**KEY POINT:** The development process focused on honest validation and failure handling.

**TRANSITION:** “Together, the cases show our value.”

## 06:30–06:50 — Impact and close

**ON SCREEN:**

1. Scroll back to the DISP-001 recommendation card.
2. End with **Human review required**, **Why this outcome?**, and the evidence summary visible.
3. Hold the final screen for two seconds after the last sentence.

**NARRATION:**

“NS01 used GPS to resolve conflicting claims. RT01 produced a transparent partial refund. DISP-001 recognised driver context and stopped at human review. RydeResolve makes dispute recommendations easier to inspect, more consistent, and clearer for both parties, while keeping people in control when policy requires it. Thank you.”

**KEY POINT:** The conclusion ties evidence, proportionality, fairness, and human oversight back to the challenge.

**TRANSITION:** End recording after the two-second hold.

## Accuracy notes for the presenter

- Say **“organiser-provided Policy v2.1 reference”**, not “Ryde’s deployed production policy.”
- Say **“recommendation”** or **“proposed refund”**, never “payment issued.”
- Describe confidence as a model self-assessment or prototype heuristic, not calibrated accuracy.
- The three agent cards describe configured roles. Separate advocate reports are not returned to the frontend.
- The frontend sends one request to the published Tencent ADP application, which manages the agent workflow internally.
- Do not claim CodeBuddy or WorkBuddy use in the narration unless you have separate genuine development evidence. The repository contains suggested CodeBuddy prompts, but that is not proof they were used.
