"""Run with: python -m streamlit run app.py"""
import copy
import json
from pathlib import Path

import streamlit as st

from disputes.adp import ADPClient, ADPError, settings
from disputes.core import OutputError, build_evidence_timeline, load_cases, load_policy, money, resolve, save_result

ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title="Ride Dispute Review", page_icon="⚖️", layout="wide")
st.markdown("""<style>
.block-container {max-width: 1200px; padding-top: 2rem;}
[data-testid="stMetric"] {border:1px solid #e2e8f0; padding:1rem; border-radius:12px;}
</style>""", unsafe_allow_html=True)
st.title("Ride Dispute Review")
st.caption("Synthetic trip evidence · Demo policy v1 · Simulated recommendations")
cases = load_cases()
with st.sidebar:
    st.header("Investigation")
    mode_label = st.radio("Agent mode", ["Offline demo", "ADP multi-agent", "ADP standard mode"])
    if mode_label == "Offline demo":
        mode = "offline"
    elif mode_label == "ADP multi-agent":
        mode = "multi_agent"
    else:
        mode = "adp"
    selected_id = st.selectbox("Sample dispute", [c["trip_id"] for c in cases],
                               format_func=lambda key: f'{key} · {next(c["title"] for c in cases if c["trip_id"] == key)}')
    st.divider()
    st.write("**Supported categories**")
    st.write("Route deviation and no-show charges")
    if mode == "multi_agent":
        st.caption("One request goes to the published multi-agent app. ADP handles Rider Advocate, Driver Advocate and Judge handoffs internally.")
    else:
        st.caption("The three agents use separate conversation contexts. All evidence tools are read-only and bound to the selected trip.")
case = copy.deepcopy(next(c for c in cases if c["trip_id"] == selected_id))
if mode == "offline":
    st.info("Offline demo uses deterministic policies and template advocate arguments. It makes no AI calls. Use this mode to check the interface first.")
elif mode == "multi_agent":
    st.info("ADP multi-agent mode sends one request to the published application. ADP routes among the Rider Advocate, Driver Advocate and Judge agents. The backend validates the final ruling against the demo policy.")
    if not settings(ROOT).get("ADP_APP_KEY", "").strip():
        st.warning("ADP is not configured yet. Add your published application's AppKey to .env locally.")
else:
    st.info("ADP standard mode uses five separate model calls for evidence selection, both advocates and the judge. The backend validates the final recommendation against the demo policy.")
    if not settings(ROOT).get("ADP_APP_KEY", "").strip():
        st.warning("ADP is not configured yet. Follow README.md to create a published application and add its AppKey to your local .env file.")
st.subheader(case["title"])
with st.form("complaint_form"):
    complaint = st.text_area("Rider's complaint", value=case["complaint"], max_chars=2000,
                             key=f"complaint_{selected_id}")
    submitted = st.form_submit_button("Investigate dispute", type="primary")
if submitted:
    st.session_state.pop("result", None)
    st.session_state.pop("adp_debug", None)
    case["complaint"] = complaint.strip()
    if not case["complaint"]:
        st.error("Enter a complaint to investigate.")
    else:
        try:
            client = ADPClient(settings(ROOT)) if mode in {"adp", "multi_agent"} else None
            with st.status("Gathering evidence and preparing cases…" if mode != "multi_agent" else "Sending dispute to ADP multi-agent application…", expanded=True) as status:
                def progress(event):
                    if event["event"] == "tool_result":
                        st.write(f'{event["actor"]}: retrieved {event["detail"]["evidence_id"]}')
                    elif event["event"] in {"started", "case_presented", "final_recommendation", "review_required", "response_received", "model_recommendation"}:
                        st.write(f'{event["actor"]}: {event["event"].replace("_", " ")}')
                result = resolve(case, mode=mode, client=client, on_event=progress)
                save_result(result)
                st.session_state["result"] = result
                if result.get("adp_debug"):
                    st.session_state["adp_debug"] = result["adp_debug"]
                status.update(label="Investigation complete", state="complete", expanded=False)
        except ADPError as exc:
            msg = str(exc)
            # Capture debug info from the exception if available.
            debug_from_exc = getattr(exc, "debug_info", None)
            if debug_from_exc:
                st.session_state["adp_debug"] = debug_from_exc
            if "401" in msg or "AppKey" in msg or "invalid" in msg.lower():
                st.error("ADP authentication failed: " + msg)
                st.caption("The AppKey is invalid or the application is not published. Check .env and restart.")
            elif "429" in msg or "quota" in msg.lower():
                st.error("ADP quota or rate limit exceeded: " + msg)
                st.caption("Check your account's model allowance and retry later.")
            elif "timed out" in msg.lower():
                st.error("ADP request timed out: " + msg)
                st.caption("No decision was accepted. Increase ADP_TIMEOUT_SECONDS or retry.")
            elif "ended before completion" in msg.lower() or "incomplete" in msg.lower():
                st.error("ADP stream was incomplete: " + msg)
                st.caption("The SSE stream ended without a completed response. No partial decision was accepted.")
            elif "did not return valid JSON" in msg or "invalid JSON" in msg.lower():
                st.error("ADP returned non-JSON output: " + msg)
                st.caption("The Judge agent did not return structured JSON. Check the Judge prompt in the ADP console — it must require JSON only, matching the project schema. See the debug info below.")
            elif "without a text reply" in msg.lower():
                st.error("ADP completed without a reply message: " + msg)
                st.caption("No reply-type message was found in the SSE stream.")
            else:
                st.error("ADP error: " + msg)
                st.caption("No recommendation was accepted. Check the setup or retry after fixing the reported issue.")
        except OutputError as exc:
            st.error("Schema validation failed: " + str(exc))
            st.caption("ADP returned a response but it did not pass the project's result validator. No fabricated fields were accepted.")
            # Capture validation debug info if available.
            val_debug = getattr(exc, "validation_debug", None)
            if val_debug:
                st.session_state["validation_debug"] = val_debug
        except (ValueError, OSError) as exc:
            st.error("Unexpected error: " + str(exc))
            st.caption("No recommendation was accepted.")
result = st.session_state.get("result")
# Show safe debug expander when ADP debug info is available (even on error).
adp_debug = st.session_state.get("adp_debug")
if adp_debug and mode in {"adp", "multi_agent"}:
    with st.expander("ADP debug info (SSE metadata — no credentials or reasoning)"):
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
# Show validation debug expander when evidence-ID validation fails.
val_debug = st.session_state.get("validation_debug")
if val_debug and mode in {"adp", "multi_agent"}:
    with st.expander("Validation debug info (evidence IDs — no credentials or reasoning)"):
        st.write("**Judge's returned evidence_ids:**")
        st.json(val_debug.get("judge_evidence_ids"))
        st.write("**Accepted evidence IDs for this case:**")
        st.json(val_debug.get("accepted_evidence_ids"))
        st.write("**Judge's returned policy_ids:**")
        st.json(val_debug.get("judge_policy_ids"))
        st.write("**Accepted policy IDs for this case:**")
        st.json(val_debug.get("accepted_policy_ids"))
        st.write("**Full Judge JSON (as received):**")
        st.json(val_debug.get("judge_ruling_json"))
if result and result["trip_id"] == selected_id and result["mode"] == mode:
    ruling = result["ruling"]
    labels = {"refund": "Refund recommended", "no_action": "Charge retained", "human_review": "Human review required"}
    a, b, c = st.columns(3)
    a.metric("Outcome", labels[ruling["ruling"]])
    b.metric("Recommended refund", money(ruling["refund_cents"]))
    c.metric("Prototype confidence", f'{ruling["confidence"]:.0%}')
    st.caption(result["confidence_note"] + f' · Measured run time: {result["elapsed_seconds"]:.3f}s')
    summary, evidence, communication, policy_tab = st.tabs(["Decision", "Evidence", "Agent communication", "Demo policy"])
    with summary:
        st.write(ruling["rationale"])
        st.write("**Policy references:** " + ", ".join(ruling["policy_ids"]))
        st.write("**Evidence references:** " + ", ".join(ruling["evidence_ids"]))
        left, right = st.columns(2)
        with left:
            st.subheader("For the rider")
            st.write(ruling["rider_message"])
        with right:
            st.subheader("For the driver")
            st.write(ruling["driver_message"])
        st.caption("No payment is executed and no message is sent to either party.")
    with evidence:
        st.write("**Python-calculated metrics**")
        st.json(result["metrics"])
        st.divider()
        timeline = build_evidence_timeline(case)
        if timeline:
            st.write("**Evidence timeline (Asia/Singapore time)**")
            st.caption("Claims are text from chat messages; observations are GPS/telemetry events (arrival, presence samples, cancellation).")
            for entry in timeline:
                tag = "Claim" if entry["type"] == "claim" else "Observation"
                st.write(f'{entry["timestamp"]} — **{entry["label"]}** ({tag})')
                st.caption(entry["detail"])
            st.divider()
        else:
            st.info("No timestamped events are available for a timeline in this case.")
        for item in result["evidence"]:
            with st.expander(item["id"]):
                st.json(item)
    with communication:
        if result["advocates"]:
            left, right = st.columns(2)
            for column, (role, argument) in zip((left, right), result["advocates"].items()):
                with column:
                    st.subheader(role)
                    st.write(argument["statement"])
                    st.caption("Requested position: " + argument["position"])
                    st.caption("Cited evidence: " + ", ".join(argument["evidence_ids"]))
        else:
            st.info("In multi-agent mode, agent handoffs are managed by ADP internally. See the activity metadata below.")
        adp_activity = result.get("adp_activity", [])
        if adp_activity:
            st.divider()
            st.write("**ADP activity metadata (from SSE stream)**")
            st.caption("Real events returned by ADP. No activity is invented or inferred.")
            st.dataframe([{"Step": a.get("sequence", i + 1), "Event": a["event"],
                           "Details": json.dumps(a.get("detail", {}), ensure_ascii=False)}
                          for i, a in enumerate(adp_activity)],
                         hide_index=True)
        st.divider()
        st.write("**Backend trace**")
        st.dataframe([{"Step": e["sequence"], "Agent": e["actor"], "Action": e["event"],
                       "Details": json.dumps(e["detail"], ensure_ascii=False)} for e in result["trace"]],
                     hide_index=True)
    with policy_tab:
        policy = load_policy()
        st.warning(policy["notice"])
        st.json(policy)
    st.download_button("Download case report (JSON)", data=json.dumps(result, indent=2),
                       file_name=f'{selected_id}_{result["mode"]}_report.json', mime="application/json")
else:
    with st.expander("Preview this trip's synthetic evidence"):
        st.json({k: v for k, v in case.items() if k not in {"complaint", "title"}})
st.divider()
st.caption("Next development step: open CODEBUDDY_START.md in CodeBuddy, add the evidence timeline, and save screenshots of your development conversations.")
