"""Streamlit app — Ride Dispute Review.

Run with: python -m streamlit run app.py

The only user-facing mode is ADP multi-agent: one request goes to the
published Tencent ADP application, which routes among Rider Advocate,
Driver Advocate and Judge agents internally. The backend validates the
Judge's final ruling against the demo policy and evidence IDs.
"""
import copy
import json
from pathlib import Path

import streamlit as st

from disputes.adp import ADPClient, ADPError, settings
from disputes.core import (
    OutputError, build_evidence_timeline, load_cases, load_policy,
    money, resolve, save_result,
)

ROOT = Path(__file__).resolve().parent

# ── Page config ──────────────────────────────────────────────────────
st.set_page_config(page_title="Ride Dispute Review", page_icon="⚖", layout="wide")

st.markdown("""
<style>
.block-container {max-width: 1080px; padding-top: 1.5rem; padding-bottom: 2rem;}
[data-testid="stMetric"] {
    border: 1px solid #e2e8f0; padding: 0.75rem 1rem; border-radius: 10px;
    background: #fafbfc;
}
[data-testid="stMetricLabel"] {font-size: 0.8rem; color: #64748b;}
[data-testid="stMetricValue"] {font-size: 1.25rem; font-weight: 600;}
.stTabs [data-baseweb="tab-list"] {gap: 0.5rem;}
.stTabs [data-baseweb="tab"] {
    padding: 0.5rem 1rem; border-radius: 8px 8px 0 0;
    font-size: 0.9rem; font-weight: 500;
}
.stTabs [aria-selected="true"] {background: #f1f5f9;}
hr {margin: 1.5rem 0; border: none; border-top: 1px solid #e2e8f0;}
</style>
""", unsafe_allow_html=True)

# ── Header ───────────────────────────────────────────────────────────
st.title("Ride Dispute Review")
st.markdown("**Evidence-based dispute recommendations with three specialised AI agents.**")
st.caption("Synthetic demonstration · Recommendations only")

cases = load_cases()
case_map = {c["trip_id"]: c for c in cases}

# ── Sidebar ──────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Case selection")
    selected_id = st.selectbox(
        "Sample dispute",
        [c["trip_id"] for c in cases],
        format_func=lambda key: f'{key} · {case_map[key]["title"]}',
    )
    case = copy.deepcopy(case_map[selected_id])

    st.divider()
    st.write("**Case summary**")
    st.write(f"Case ID: `{case["trip_id"]}`")
    st.write(f"Category: `{case["category"].replace("_", " ").title()}`")
    st.write(f"Title: {case["title"]}")
    payment = case["payment"]
    st.write(f"Charged: {money(payment["charged_cents"])}")
    if payment.get("cancellation_fee_cents"):
        st.write(f"Cancellation fee: {money(payment["cancellation_fee_cents"])}")
    if payment.get("reference_fare_cents"):
        st.write(f"Reference fare: {money(payment["reference_fare_cents"])}")

    st.divider()
    st.write("**Connection status**")
    adp_config = settings(ROOT)
    app_key = adp_config.get("ADP_APP_KEY", "").strip()
    if app_key and app_key != "your_actual_published_appkey_here":
        st.success("ADP AppKey configured")
    else:
        st.warning("ADP AppKey not set")
    st.caption("Set ADP_APP_KEY in the server environment or local `.env`.")

# ── Main input area ──────────────────────────────────────────────────
st.subheader(case["title"])
with st.form("complaint_form"):
    complaint = st.text_area(
        "Rider's complaint",
        value=case["complaint"],
        max_chars=2000,
        key=f"complaint_{selected_id}",
    )
    submitted = st.form_submit_button("Investigate dispute", type="primary")

# Track execution state to prevent duplicate submissions.
if "executing" not in st.session_state:
    st.session_state["executing"] = False

if submitted and not st.session_state["executing"]:
    st.session_state["executing"] = True
    st.session_state.pop("result", None)
    st.session_state.pop("adp_debug", None)
    st.session_state.pop("validation_debug", None)
    case["complaint"] = complaint.strip()
    if not case["complaint"]:
        st.error("Enter a complaint to investigate.")
    else:
        try:
            client = ADPClient(settings(ROOT))
            with st.status("Sending dispute to ADP multi-agent application…", expanded=True) as status:
                def progress(event):
                    if event["event"] == "tool_result":
                        st.write(f'Retrieved {event["detail"]["evidence_id"]}')
                    elif event["event"] in {"started", "evidence_gathered",
                                            "response_received", "model_recommendation",
                                            "review_required", "final_recommendation"}:
                        label = event["event"].replace("_", " ")
                        st.write(f'{event["actor"]}: {label}')

                result = resolve(case, mode="multi_agent", client=client, on_event=progress)
                save_result(result)
                st.session_state["result"] = result
                if result.get("adp_debug"):
                    st.session_state["adp_debug"] = result["adp_debug"]
                status.update(label="Investigation complete", state="complete", expanded=False)
        except ADPError as exc:
            msg = str(exc)
            debug_from_exc = getattr(exc, "debug_info", None)
            if debug_from_exc:
                st.session_state["adp_debug"] = debug_from_exc
            if "401" in msg or "AppKey" in msg or "invalid" in msg.lower():
                st.error("ADP authentication failed: " + msg)
                st.caption("The AppKey is invalid or the application is not published. Check the environment variable or `.env` and restart.")
            elif "429" in msg or "quota" in msg.lower():
                st.error("ADP quota or rate limit exceeded: " + msg)
                st.caption("Check your account's model allowance and retry later.")
            elif "timed out" in msg.lower():
                st.error("ADP request timed out: " + msg)
                st.caption("No decision was accepted. Increase `ADP_TIMEOUT_SECONDS` or retry.")
            elif "ended before completion" in msg.lower() or "incomplete" in msg.lower():
                st.error("ADP stream was incomplete: " + msg)
                st.caption("The SSE stream ended without a completed response. No partial decision was accepted.")
            elif "did not return valid JSON" in msg or "invalid JSON" in msg.lower():
                st.error("ADP returned non-JSON output: " + msg)
                st.caption("The Judge agent did not return structured JSON. Check the Judge prompt in the ADP console. See diagnostics below.")
            elif "without a text reply" in msg.lower():
                st.error("ADP completed without a reply message: " + msg)
                st.caption("No reply-type message was found in the SSE stream.")
            else:
                st.error("ADP error: " + msg)
                st.caption("No recommendation was accepted. Check the setup or retry after fixing the reported issue.")
        except OutputError as exc:
            st.error("Schema validation failed: " + str(exc))
            st.caption("ADP returned a response but it did not pass the project's result validator. No fabricated fields were accepted.")
            val_debug = getattr(exc, "validation_debug", None)
            if val_debug:
                st.session_state["validation_debug"] = val_debug
        except (ValueError, OSError) as exc:
            st.error("Unexpected error: " + str(exc))
            st.caption("No recommendation was accepted.")
    st.session_state["executing"] = False

# ── Diagnostics (secondary expanders) ────────────────────────────────
adp_debug = st.session_state.get("adp_debug")
if adp_debug:
    with st.expander("Technical diagnostics — SSE metadata"):
        st.write("**Event types received:**")
        st.text(", ".join(adp_debug.get("event_types", [])))
        st.write(f"**Completion status:** `{adp_debug.get('completion_status', 'N/A')}`")
        st.write(f"**Activity events:** {adp_debug.get('activity_event_count', 0)}")
        msg_ids = adp_debug.get("message_ids", [])
        if msg_ids:
            st.write("**Messages by MessageId:**")
            st.dataframe(msg_ids, hide_index=True)
        final_text = adp_debug.get("final_reply_text", "")
        if final_text:
            st.write("**Final reply text (raw, as parsed from SSE):**")
            st.code(final_text[:5000], language="text")
            if len(final_text) > 5000:
                st.caption(f"Truncated — full text is {len(final_text)} characters.")
        else:
            st.caption("No final reply text was captured.")

val_debug = st.session_state.get("validation_debug")
if val_debug:
    with st.expander("Validation diagnostics — evidence and policy IDs"):
        col_a, col_b = st.columns(2)
        with col_a:
            st.write("**Judge's evidence_ids:**")
            st.json(val_debug.get("judge_evidence_ids"))
            st.write("**Accepted evidence IDs:**")
            st.json(val_debug.get("accepted_evidence_ids"))
        with col_b:
            st.write("**Judge's policy_ids:**")
            st.json(val_debug.get("judge_policy_ids"))
            st.write("**Accepted policy IDs:**")
            st.json(val_debug.get("accepted_policy_ids"))
        st.write("**Full Judge JSON (as received):**")
        st.json(val_debug.get("judge_ruling_json"))

# ── Result area ──────────────────────────────────────────────────────
result = st.session_state.get("result")
if result and result.get("trip_id") == selected_id:
    ruling = result["ruling"]
    labels = {
        "refund": "Refund recommended",
        "no_action": "Charge retained",
        "human_review": "Human review required",
    }

    # Top-line metrics.
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Outcome", labels[ruling["ruling"]])
    col_b.metric("Proposed refund", money(ruling["refund_cents"]))
    if ruling["ruling"] == "human_review":
        col_c.metric("Review required", "Yes")
    else:
        col_c.metric("Prototype confidence", f'{ruling["confidence"]:.0%}')
    st.caption(result["confidence_note"] + f" · Measured run time: {result["elapsed_seconds"]:.3f}s")

    # Public rationale.
    st.write(ruling["rationale"])
    st.caption("**Policy references:** " + ", ".join(ruling["policy_ids"]))
    st.caption("**Evidence references:** " + ", ".join(ruling["evidence_ids"]))

    # ── Tabs ─────────────────────────────────────────────────────────
    tab_review, tab_evidence, tab_messages = st.tabs([
        "Agent review", "Evidence and policy", "Proposed party messages",
    ])

    # ── Tab 1: Agent review ─────────────────────────────────────────
    with tab_review:
        advocates = result.get("advocates", {})
        adp_activity = result.get("adp_activity", [])

        # Extract agent names and message metadata from SSE activity.
        agent_messages: list[dict] = []
        for a in adp_activity:
            detail = a.get("detail", {})
            agent_name = detail.get("agent", "")
            msg_type = detail.get("type", "")
            if agent_name and msg_type:
                agent_messages.append({
                    "agent": agent_name,
                    "type": msg_type,
                    "status": detail.get("status", ""),
                    "event": a.get("event", ""),
                })

        if advocates:
            # Structured advocate reports available (offline/adp modes returned them).
            col_left, col_right = st.columns(2)
            for column, (role, argument) in zip((col_left, col_right), advocates.items()):
                with column:
                    st.subheader(role)
                    st.write(argument["statement"])
                    pos_labels = {"refund": "Refund", "no_action": "Retain charge", "human_review": "Review"}
                    st.caption(f"Position: {pos_labels.get(argument["position"], argument["position"])}")
                    st.caption("Cited evidence: " + ", ".join(argument["evidence_ids"]))
        else:
            # Multi-agent mode: ADP manages advocate handoffs internally.
            # The Judge's ruling is the only structured output we receive.
            # Show agent activity metadata from the SSE stream.
            st.write("##### Rider Advocate")
            st.caption("Rider Advocate analysis is managed internally by ADP.")
            st.info(
                "The Rider Advocate's report is not returned as a separate structured "
                "output in the current multi-agent response. The Judge's ruling below "
                "summarises the competing arguments. See the note at the bottom of this tab."
            )

            st.write("##### Driver Advocate")
            st.caption("Driver Advocate analysis is managed internally by ADP.")
            st.info(
                "The Driver Advocate's report is not returned as a separate structured "
                "output in the current multi-agent response. The Judge's ruling below "
                "summarises the competing arguments."
            )

        # Judge section.
        st.write("##### Judge")
        st.write(ruling["rationale"])
        st.caption(f"Ruling: {labels[ruling["ruling"]]} · Refund: {money(ruling["refund_cents"])}")
        st.caption("Cited evidence: " + ", ".join(ruling["evidence_ids"]))
        st.caption("Cited policy: " + ", ".join(ruling["policy_ids"]))

        # ADP activity metadata table.
        if adp_activity:
            st.divider()
            st.write("**ADP activity (from SSE stream)**")
            st.caption("Real events returned by ADP. No activity is invented or inferred.")
            st.dataframe(
                [{"Step": a.get("sequence", i + 1),
                  "Event": a["event"],
                  "Details": json.dumps(a.get("detail", {}), ensure_ascii=False)}
                 for i, a in enumerate(adp_activity)],
                hide_index=True,
            )

        # Backend trace.
        st.write("**Backend trace**")
        st.dataframe(
            [{"Step": e["sequence"], "Agent": e["actor"], "Action": e["event"],
              "Details": json.dumps(e["detail"], ensure_ascii=False)}
             for e in result["trace"]],
            hide_index=True,
        )

        # Gap explanation.
        if not advocates:
            st.divider()
            with st.expander("Why are advocate reports not shown separately?"):
                st.write(
                    "In multi-agent mode, ADP routes among the Rider Advocate, Driver "
                    "Advocate and Judge agents internally. The SSE stream returns "
                    "multiple `reply` messages, but the backend parser selects only "
                    "the **last** reply — the Judge's final ruling — to ensure valid "
                    "JSON. Advocate reports and tool outputs are excluded from the "
                    "returned text but their metadata appears in the activity table "
                    "above.\n\n"
                    "To display separate structured advocate reports, the ADP Judge "
                    "prompt would need to include advocate summaries in its JSON "
                    "output. See the schema-change note below."
                )
                st.write("**Proposed smallest schema addition:**")
                st.code(json.dumps({
                    "rider_advocate_summary": "<string — Judge's summary of the rider advocate's case>",
                    "driver_advocate_summary": "<string — Judge's summary of the driver advocate's case>",
                }, indent=2), language="json")
                st.write(
                    "These would be **Judge-generated summaries**, not verbatim "
                    "advocate reports. They must be labelled as summaries in the UI. "
                    "The ADP Judge prompt would need one additional instruction line: "
                    '`"rider_advocate_summary": summarise the Rider Advocate\'s main '
                    'argument in 1-2 sentences. '
                    '"driver_advocate_summary": summarise the Driver Advocate\'s main '
                    'argument in 1-2 sentences.`'
                )

    # ── Tab 2: Evidence and policy ──────────────────────────────────
    with tab_evidence:
        st.write("**Python-calculated metrics**")
        st.json(result["metrics"])
        st.divider()

        timeline = build_evidence_timeline(case)
        if timeline:
            st.write("**Evidence timeline (Asia/Singapore time)**")
            st.caption("Claims are text from chat messages; observations are GPS/telemetry events.")
            for entry in timeline:
                tag = "Claim" if entry["type"] == "claim" else "Observation"
                st.write(f'{entry["timestamp"]} — **{entry["label"]}** ({tag})')
                st.caption(entry["detail"])
            st.divider()
        else:
            st.info("No timestamped events are available for a timeline in this case.")

        st.write("**Evidence records**")
        for item in result["evidence"]:
            with st.expander(item["id"]):
                st.json(item)

        st.divider()
        st.write("**Demo policy**")
        policy = load_policy()
        st.warning(policy["notice"])
        st.json(policy)

    # ── Tab 3: Proposed party messages ──────────────────────────────
    with tab_messages:
        col_left, col_right = st.columns(2)
        with col_left:
            st.subheader("For the rider")
            st.write(ruling["rider_message"])
        with col_right:
            st.subheader("For the driver")
            st.write(ruling["driver_message"])
        st.caption("No payment is executed and no message is sent to either party.")

    # ── JSON download (secondary control) ───────────────────────────
    with st.expander("Download case report (JSON)"):
        st.download_button(
            "Download report",
            data=json.dumps(result, indent=2),
            file_name=f'{selected_id}_multi_agent_report.json',
            mime="application/json",
        )

elif result and result.get("trip_id") != selected_id:
    st.info(f"The displayed result is for case `{result["trip_id"]}`. Select that case to view it again, or investigate the current case.")

else:
    with st.expander("Preview this trip's synthetic evidence"):
        st.json({k: v for k, v in case.items() if k not in {"complaint", "title"}})

st.divider()
st.caption("Ride Dispute Review · Synthetic demonstration · Recommendations only · No payment is executed.")
