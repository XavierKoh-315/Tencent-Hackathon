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

PRIMARY_GREEN = "#0d7a5e"
DARK_GREEN = "#1a3c34"
MINT_BG = "#f0f9f6"
MINT_CARD = "#e8f5f0"
WHITE = "#ffffff"
BORDER = "#e2e8f0"
MUTED = "#64748b"
TEXT = "#1f2937"


def _css():
    st.markdown(f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    html, body, [class*="css"] {{
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }}

    /* Page background */
    .stApp {{
        background: {MINT_BG};
    }}

    /* Main content width and padding */
    .block-container {{
        max-width: 1100px;
        padding: 0 1.5rem 3rem 1.5rem;
    }}

    /* Sidebar: pale mint background */
    [data-testid="stSidebar"] {{
        background: {MINT_BG} !important;
    }}
    [data-testid="stSidebar"] > div:first-child {{
        background: {MINT_BG};
    }}

    /* Hide default Streamlit header/title in main */
    #MainMenu {{visibility: hidden;}}
    header {{visibility: hidden;}}

    /* Buttons */
    .stButton > button {{
        border-radius: 8px;
        font-weight: 500;
        transition: all 0.15s ease;
    }}
    .stButton > button[kind="primary"] {{
        background: {PRIMARY_GREEN};
        border: 1px solid {PRIMARY_GREEN};
        color: white;
    }}
    .stButton > button[kind="primary"]:hover {{
        background: #0a6b52;
        border-color: #0a6b52;
    }}
    .stButton > button[kind="secondary"]:hover {{
        border-color: {PRIMARY_GREEN};
        color: {PRIMARY_GREEN};
    }}

    /* Form inputs */
    .stTextArea textarea {{
        background: {WHITE};
        border: 1px solid {BORDER};
        border-radius: 10px;
        font-size: 0.95rem;
        line-height: 1.5;
    }}
    .stTextArea textarea:focus {{
        border-color: {PRIMARY_GREEN};
        box-shadow: 0 0 0 3px rgba(13, 122, 94, 0.08);
    }}

    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {{
        gap: 0.25rem;
        border-bottom: 1px solid {BORDER};
    }}
    .stTabs [data-baseweb="tab"] {{
        padding: 0.6rem 1rem;
        border-radius: 8px 8px 0 0;
        font-size: 0.9rem;
        font-weight: 500;
        color: {MUTED};
        background: transparent;
        border: none;
    }}
    .stTabs [data-baseweb="tab"]:hover {{
        color: {DARK_GREEN};
        background: rgba(13, 122, 94, 0.04);
    }}
    .stTabs [aria-selected="true"] {{
        color: {PRIMARY_GREEN} !important;
        background: {MINT_CARD} !important;
        border-bottom: 2px solid {PRIMARY_GREEN};
    }}

    /* Expander */
    .streamlit-expanderHeader {{
        font-size: 0.9rem;
        font-weight: 500;
        color: {MUTED};
        border-radius: 8px;
    }}
    .streamlit-expanderHeader:hover {{
        color: {DARK_GREEN};
    }}

    /* Dataframe */
    .stDataFrame {{border-radius: 10px; overflow: hidden;}}

    /* Markdown typography helpers */
    .eyebrow {{
        color: {PRIMARY_GREEN};
        font-size: 0.7rem;
        font-weight: 700;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        margin-bottom: 0.25rem;
    }}
    .page-title {{
        color: {DARK_GREEN};
        font-size: 1.85rem;
        font-weight: 700;
        line-height: 1.2;
        margin: 0;
    }}
    .page-subtitle {{
        color: {MUTED};
        font-size: 0.95rem;
        margin-top: 0.25rem;
    }}
    .card {{
        background: {WHITE};
        border: 1px solid {BORDER};
        border-radius: 12px;
        padding: 1.25rem;
        box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    }}
    .card-title {{
        color: {DARK_GREEN};
        font-size: 1rem;
        font-weight: 600;
        margin: 0 0 0.5rem 0;
    }}
    .muted {{ color: {MUTED}; font-size: 0.85rem; }}
    .small {{ font-size: 0.8rem; }}
    .badge {{
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
        padding: 0.35rem 0.75rem;
        border-radius: 999px;
        font-size: 0.75rem;
        font-weight: 600;
    }}
    .badge-green {{
        background: {MINT_CARD};
        color: {PRIMARY_GREEN};
        border: 1px solid #c5e8dc;
    }}
    .badge-amber {{
        background: #fffbeb;
        color: #b45309;
        border: 1px solid #fde68a;
    }}
    .badge-grey {{
        background: #f3f4f6;
        color: #4b5563;
        border: 1px solid #e5e7eb;
    }}

    /* Resolution card metric columns */
    .metric-label {{ color: {MUTED}; font-size: 0.75rem; font-weight: 500; margin-bottom: 0.25rem; }}
    .metric-value {{ color: {DARK_GREEN}; font-size: 1.5rem; font-weight: 700; }}
    .metric-sub {{ color: {MUTED}; font-size: 0.75rem; margin-top: 0.25rem; }}

    /* Activity timeline */
    .timeline {{ position: relative; padding-left: 1.25rem; }}
    .timeline::before {{
        content: "";
        position: absolute;
        left: 0.25rem;
        top: 0.35rem;
        bottom: 0.35rem;
        width: 2px;
        background: {BORDER};
    }}
    .timeline-item {{ position: relative; margin-bottom: 1rem; }}
    .timeline-item::before {{
        content: "";
        position: absolute;
        left: -1.05rem;
        top: 0.35rem;
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: {BORDER};
    }}
    .timeline-item.active::before {{ background: {PRIMARY_GREEN}; }}
    .timeline-title {{ font-weight: 600; color: {TEXT}; font-size: 0.9rem; }}
    .timeline-detail {{ color: {MUTED}; font-size: 0.8rem; }}

    /* Agent cards */
    .agent-card {{
        background: {WHITE};
        border: 1px solid {BORDER};
        border-radius: 12px;
        padding: 1rem;
        height: 100%;
    }}
    .agent-icon {{
        width: 32px;
        height: 32px;
        border-radius: 8px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        font-size: 1rem;
        margin-bottom: 0.5rem;
    }}
    .agent-name {{ font-weight: 600; color: {DARK_GREEN}; font-size: 0.95rem; }}
    .agent-role {{ color: {MUTED}; font-size: 0.75rem; margin-bottom: 0.5rem; }}

    /* Sidebar radio-as-cards */
    [data-testid="stSidebar"] [role="radiogroup"] {{
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
    }}
    [data-testid="stSidebar"] [role="radio"] {{
        display: none;
    }}
    [data-testid="stSidebar"] [data-baseweb="radio"] {{
        display: block;
        border: 1px solid {BORDER};
        border-radius: 10px;
        padding: 0.65rem 0.75rem;
        background: {WHITE};
        cursor: pointer;
        transition: all 0.15s ease;
    }}
    [data-testid="stSidebar"] [data-baseweb="radio"]:hover {{
        border-color: #c5e8dc;
        background: {MINT_CARD};
    }}
    [data-testid="stSidebar"] [data-baseweb="radio"][aria-checked="true"] {{
        border-left: 3px solid {PRIMARY_GREEN};
        background: {MINT_CARD};
        border-color: #c5e8dc;
    }}
    [data-testid="stSidebar"] [data-baseweb="radio"] > div:last-child {{
        margin-left: 0 !important;
    }}

    /* Compact sidebar typography */
    .queue-id {{ color: {MUTED}; font-size: 0.7rem; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; }}
    .queue-title {{ color: {DARK_GREEN}; font-size: 0.82rem; font-weight: 600; line-height: 1.3; }}
    .queue-meta {{ color: {MUTED}; font-size: 0.72rem; }}

    /* Top bar */
    .top-bar {{
        background: {WHITE};
        border-bottom: 1px solid {BORDER};
        padding: 0.75rem 1.5rem;
        margin: -1rem -1.5rem 1.5rem -1.5rem;
        display: flex;
        align-items: center;
        justify-content: space-between;
    }}
    </style>
    """, unsafe_allow_html=True)


# ── Page config ─────────────────────────────────────────────────────────
st.set_page_config(page_title="Ride Dispute Review", page_icon="⚖", layout="wide")
_css()

# ── Data load ───────────────────────────────────────────────────────────
cases = load_cases()
case_map = {c["trip_id"]: c for c in cases}

# Session-state initialisation.
if "selected_case" not in st.session_state:
    st.session_state["selected_case"] = cases[0]["trip_id"]
if "executing" not in st.session_state:
    st.session_state["executing"] = False

selected_id = st.session_state["selected_case"]
case = copy.deepcopy(case_map[selected_id])


def _format_category(cat: str) -> str:
    return cat.replace("_", " ").title()


# ── Sidebar ─────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("**Case Queue**")

    def _select_label(key: str) -> str:
        c = case_map[key]
        return f"{c['trip_id']} — {c['title']}"

    selected = st.selectbox(
        "Select a case",
        options=[c["trip_id"] for c in cases],
        format_func=_select_label,
        index=[c["trip_id"] for c in cases].index(st.session_state["selected_case"]),
        key="case_select",
    )

    if selected != st.session_state["selected_case"]:
        st.session_state["selected_case"] = selected
        st.session_state.pop("result", None)
        st.session_state.pop("adp_debug", None)
        st.session_state.pop("validation_debug", None)
        st.rerun()


# ── Top bar ─────────────────────────────────────────────────────────────
result = st.session_state.get("result")
status_badge = ""
if result and result.get("trip_id") == selected_id:
    status_badge = '<span class="badge badge-green"><span>✓</span> Investigation complete</span>'
else:
    status_badge = '<span class="badge badge-grey">Ready to investigate</span>'

st.markdown(f"""
<div class="top-bar">
    <div style="display:flex;align-items:center;gap:0.5rem;font-size:0.85rem;color:#64748b;">
        <span>Disputes</span>
        <span style="color:#cbd5e1;">/</span>
        <span style="font-weight:600;color:#1a3c34;">Case {selected_id}</span>
    </div>
    <div style="display:flex;align-items:center;gap:0.75rem;">
        <span class="badge badge-grey">DEMO ENVIRONMENT</span>
        <div style="width:28px;height:28px;border-radius:50%;background:#e8f5f0;display:flex;align-items:center;justify-content:center;color:#0d7a5e;font-weight:600;font-size:0.75rem;border:1px solid #c5e8dc;">JD</div>
    </div>
</div>
""", unsafe_allow_html=True)


# ── Page heading ────────────────────────────────────────────────────────
head_col1, head_col2 = st.columns([3, 1])
with head_col1:
    st.markdown('<div class="eyebrow">Evidence-led resolution</div>', unsafe_allow_html=True)
    st.markdown('<h1 class="page-title">Ride Dispute Review</h1>', unsafe_allow_html=True)
    st.markdown('<div class="page-subtitle">Three specialised AI agents. Every perspective considered.</div>', unsafe_allow_html=True)
with head_col2:
    st.markdown(f"""
    <div style="display:flex;justify-content:flex-end;align-items:flex-end;height:100%;padding-bottom:0.35rem;">
        {status_badge}
    </div>
    """, unsafe_allow_html=True)

st.markdown("<div style='margin-bottom:1.25rem;'></div>", unsafe_allow_html=True)


# ── Complaint card ─────────────────────────────────────────────────────-
with st.form("complaint_form"):
    st.markdown(f"""
    <div class="card">
        <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.35rem;">
            <span class="queue-id">{selected_id} · {_format_category(case['category'])}</span>
            <span class="badge badge-grey" style="margin-left:auto;">Rider-submitted dispute</span>
        </div>
        <div class="card-title" style="font-size:1.15rem;margin-bottom:0.75rem;">{case['title']}</div>
        <div style="background:#f8fafb;border:1px solid {BORDER};border-radius:10px;padding:0.9rem 1rem;margin-bottom:1rem;">
            <div style="display:flex;align-items:center;gap:0.4rem;color:#64748b;font-size:0.75rem;font-weight:600;margin-bottom:0.4rem;text-transform:uppercase;letter-spacing:0.04em;">
                <span style="font-size:0.9rem;">❝</span> Rider's complaint
            </div>
    """, unsafe_allow_html=True)

    complaint = st.text_area(
        "Rider's complaint",
        value=case["complaint"],
        max_chars=2000,
        key=f"complaint_{selected_id}",
        label_visibility="collapsed",
        height=90,
    )

    st.markdown("</div>", unsafe_allow_html=True)

    c1, c2 = st.columns([4, 1])
    with c2:
        submitted = st.form_submit_button("⚡ Investigate dispute", type="primary", use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)


# ── Investigation handling (behaviour preserved) ────────────────────────
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


# ── Diagnostics (secondary expanders, kept available) ───────────────────
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


# ── Result area ─────────────────────────────────────────────────────────
result = st.session_state.get("result")
if result and result.get("trip_id") == selected_id:
    ruling = result["ruling"]
    labels = {
        "refund": "Refund recommended",
        "no_action": "Charge retained",
        "human_review": "Human review required",
    }
    outcome_label = labels[ruling["ruling"]]
    human_review = ruling["ruling"] == "human_review"

    # Resolution card
    st.markdown("<div style='margin-top:1.25rem;'></div>", unsafe_allow_html=True)
    st.markdown(f"""
    <div class="card" style="background:{MINT_CARD};border-color:#c5e8dc;">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:1rem;">
            <div style="display:flex;align-items:center;gap:0.5rem;">
                <span style="font-size:1rem;">🛡</span>
                <span style="font-weight:600;color:#1a3c34;font-size:0.9rem;">Resolution recommendation</span>
            </div>
            {"" + (f'<span class="badge badge-amber">Human review required</span>' if human_review else f'<span class="badge badge-grey">AI recommendation</span>') + ""}
        </div>
        <div style="display:grid;grid-template-columns:1.2fr 1fr 1fr;gap:1.5rem;">
            <div style="border-right:1px solid #c5e8dc;padding-right:1rem;">
                <div class="metric-label">Recommended outcome</div>
                <div class="metric-value" style="display:flex;align-items:center;gap:0.5rem;">
                    {"" + (f'<span style="width:28px;height:28px;border-radius:50%;background:#0d7a5e;color:white;display:inline-flex;align-items:center;justify-content:center;font-size:0.9rem;">✓</span>' if ruling["ruling"] == "refund" else '') + ""}
                    {outcome_label}
                </div>
                <div class="metric-sub">{result['policy_version']}</div>
            </div>
            <div style="border-right:1px solid #c5e8dc;padding-right:1rem;">
                <div class="metric-label">Proposed refund</div>
                <div class="metric-value">{money(ruling["refund_cents"])}</div>
                <div class="metric-sub">Calculated under {ruling['policy_ids'][0] if ruling['policy_ids'] else 'policy'}</div>
            </div>
            <div>
                <div class="metric-label">Prototype confidence</div>
                <div class="metric-value">{ruling['confidence']:.0%}</div>
                <div class="metric-sub">Model self-assessment</div>
            </div>
        </div>
        <div style="margin-top:0.75rem;padding-top:0.75rem;border-top:1px solid #c5e8dc;">
            <span class="muted" style="font-size:0.75rem;">Recommendation only. Confidence is a prototype heuristic, not calibrated accuracy. · Measured run time: {result["elapsed_seconds"]:.3f}s</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Explanation + evidence cards
    st.markdown("<div style='margin-top:1.25rem;'></div>", unsafe_allow_html=True)
    why_col, ev_col = st.columns([2, 1])

    with why_col:
        st.markdown(f"""
        <div class="card" style="height:100%;">
            <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.75rem;">
                <span style="font-size:1rem;">📋</span>
                <span class="card-title" style="margin:0;">Why this outcome?</span>
            </div>
            <div style="color:#1f2937;font-size:0.95rem;line-height:1.6;margin-bottom:1rem;">
                {ruling["rationale"]}
            </div>
            <div style="display:flex;align-items:center;gap:0.4rem;color:#0d7a5e;font-size:0.8rem;font-weight:500;">
                <span>✓</span> Grounded in trip, message, route and payment evidence
            </div>
        </div>
        """, unsafe_allow_html=True)

    with ev_col:
        metrics = result["metrics"]
        ev_rows = []
        cat = result["category"]
        if cat == "route_deviation":
            if metrics.get("actual_distance_m") is not None:
                ev_rows.append(("Actual route", f"{metrics['actual_distance_m']/1000:.2f} km"))
            if metrics.get("reference_distance_m") is not None:
                ev_rows.append(("Reference route", f"{metrics['reference_distance_m']/1000:.2f} km"))
            if metrics.get("deviation_ratio") is not None:
                ev_rows.append(("Deviation", f"{metrics['deviation_ratio']:.1%}"))
        elif cat in ("no_show", "no_show_charge"):
            if metrics.get("max_pickup_distance_m") is not None:
                ev_rows.append(("Max pickup distance", f"{metrics['max_pickup_distance_m']:.1f} m"))
            if metrics.get("verified_wait_seconds") is not None:
                ev_rows.append(("Verified wait", f"{metrics['verified_wait_seconds']/60:.1f} min"))
        elif cat == "fare_dispute":
            if metrics.get("fare_difference_cents") is not None:
                ev_rows.append(("Fare difference", money(metrics["fare_difference_cents"])))
            if metrics.get("surge_difference_cents") is not None:
                ev_rows.append(("Surge difference", money(metrics["surge_difference_cents"])))

        ev_html = "\n".join(
            f'<div style="display:flex;justify-content:space-between;align-items:center;padding:0.5rem 0;border-bottom:1px solid {BORDER};"><span class="muted">{k}</span><span style="font-weight:600;color:#1a3c34;">{v}</span></div>'
            for k, v in ev_rows
        )

        st.markdown(f"""
        <div class="card" style="height:100%;">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:0.75rem;">
                <div style="display:flex;align-items:center;gap:0.5rem;">
                    <span style="font-size:1rem;">🧩</span>
                    <span class="card-title" style="margin:0;">Evidence at a glance</span>
                </div>
            </div>
            {ev_html}
        </div>
        """, unsafe_allow_html=True)

    # ── Tabs ────────────────────────────────────────────────────────────
    st.markdown("<div style='margin-top:1.25rem;'></div>", unsafe_allow_html=True)
    tab_review, tab_evidence, tab_messages = st.tabs([
        "Agent review", "Evidence & policy", "Proposed party messages",
    ])

    # ── Tab 1: Agent review ─────────────────────────────────────────────
    with tab_review:
        st.markdown("""
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:0.75rem;">
            <span class="muted">Different perspectives. One evidence-based recommendation.</span>
            <span class="badge badge-grey">Multi-agent review</span>
        </div>
        """, unsafe_allow_html=True)

        advocates = result.get("advocates", {})
        adp_activity = result.get("adp_activity", [])

        a1, a2, a3 = st.columns(3)
        with a1:
            st.markdown("""
            <div class="agent-card">
                <div class="agent-icon" style="background:#eff6ff;color:#2563eb;">👤</div>
                <div class="agent-name">Rider Advocate</div>
                <div class="agent-role">The rider's perspective</div>
                <div style="color:#374151;font-size:0.88rem;line-height:1.5;margin-bottom:0.75rem;">
                    Reviews the rider's complaint and supporting evidence for a fair remedy.
                </div>
                <div class="muted" style="display:flex;align-items:center;gap:0.35rem;">
                    <span>⚡</span> Managed internally by ADP
                </div>
            </div>
            """, unsafe_allow_html=True)
        with a2:
            st.markdown("""
            <div class="agent-card">
                <div class="agent-icon" style="background:#fff7ed;color:#ea580c;">🚕</div>
                <div class="agent-name">Driver Advocate</div>
                <div class="agent-role">The driver's perspective</div>
                <div style="color:#374151;font-size:0.88rem;line-height:1.5;margin-bottom:0.75rem;">
                    Considers driver context and any operational justification for the charge.
                </div>
                <div class="muted" style="display:flex;align-items:center;gap:0.35rem;">
                    <span>⚡</span> Managed internally by ADP
                </div>
            </div>
            """, unsafe_allow_html=True)
        with a3:
            judge_summary = ruling["rationale"]
            st.markdown(f"""
            <div class="agent-card">
                <div class="agent-icon" style="background:{MINT_CARD};color:{PRIMARY_GREEN};">⚖</div>
                <div class="agent-name">Judge</div>
                <div class="agent-role">The final synthesis</div>
                <div style="color:#374151;font-size:0.88rem;line-height:1.5;margin-bottom:0.75rem;">
                    {judge_summary}
                </div>
                <div class="muted" style="display:flex;align-items:center;gap:0.35rem;">
                    <span>✓</span> Ruling complete · {ruling['policy_ids'][0] if ruling['policy_ids'] else 'policy'}
                </div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("""
        <div style="margin-top:0.75rem;color:#64748b;font-size:0.8rem;line-height:1.4;">
            Individual advocate reports are not returned as separate structured outputs. The Judge's ruling summarises the competing arguments.
        </div>
        """, unsafe_allow_html=True)

        # Investigation activity timeline
        st.markdown("<div style='margin-top:1.5rem;'></div>", unsafe_allow_html=True)
        st.markdown("""
        <div class="card">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:1rem;">
                <div style="display:flex;align-items:center;gap:0.5rem;">
                    <span style="font-size:1rem;">📡</span>
                    <span class="card-title" style="margin:0;">Investigation activity</span>
                    <span class="badge badge-grey">ADP</span>
                </div>
                <span class="muted small">SSE event stream</span>
            </div>
        """, unsafe_allow_html=True)

        if adp_activity:
            timeline_items = []
            for i, a in enumerate(adp_activity):
                detail = a.get("detail", {})
                agent = detail.get("agent", "")
                typ = detail.get("type", "")
                event_label = a.get("event", "").replace("_", " ").title()
                title = f"{agent} {event_label}".strip() if agent else event_label
                sub = f"Event type: {typ}" if typ else f"Sequence {a.get('sequence', i+1)}"
                active = a.get("event") in {"response_received", "final_recommendation"}
                timeline_items.append(f"""
                <div class="timeline-item {'active' if active else ''}">
                    <div class="timeline-title">{title}</div>
                    <div class="timeline-detail">{sub}</div>
                </div>
                """)
            st.markdown(f'<div class="timeline">{ "".join(timeline_items) }</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="muted">No activity metadata returned for this investigation.</div>', unsafe_allow_html=True)

        st.markdown("""
            <div style="margin-top:0.75rem;padding-top:0.75rem;border-top:1px solid #e2e8f0;color:#64748b;font-size:0.75rem;line-height:1.4;">
                Readable labels for ADP stream events shown in the prototype. No internal reasoning inferred.
            </div>
        </div>
        """, unsafe_allow_html=True)

    # ── Tab 2: Evidence and policy ──────────────────────────────────────
    with tab_evidence:
        st.markdown("""
        <div class="card" style="margin-bottom:1rem;">
            <div class="card-title">Python-calculated metrics</div>
        """, unsafe_allow_html=True)
        st.json(result["metrics"])
        st.markdown("</div>", unsafe_allow_html=True)

        timeline = build_evidence_timeline(case)
        if timeline:
            st.markdown("""
            <div class="card" style="margin-bottom:1rem;">
                <div class="card-title">Evidence timeline (Asia/Singapore time)</div>
                <div class="muted" style="margin-bottom:0.75rem;">Claims are text from chat messages; observations are GPS/telemetry events.</div>
            """, unsafe_allow_html=True)
            for entry in timeline:
                tag = "Claim" if entry["type"] == "claim" else "Observation"
                st.write(f'{entry["timestamp"]} — **{entry["label"]}** ({tag})')
                st.caption(entry["detail"])
            st.markdown("</div>", unsafe_allow_html=True)
        else:
            st.info("No timestamped events are available for a timeline in this case.")

        st.markdown('<div class="card-title">Evidence records</div>', unsafe_allow_html=True)
        for item in result["evidence"]:
            with st.expander(item["id"]):
                st.json(item)

        st.markdown("<div style='margin-top:1rem;'></div>", unsafe_allow_html=True)
        st.markdown(f'<div class="card-title">Policy ({result["policy_version"]})</div>', unsafe_allow_html=True)
        if result.get("policy_version") == "organiser-v2.1":
            st.caption("Organiser-provided hackathon reference; not verified production Ryde policy.")
            pol_evidence = [e for e in result["evidence"] if e.get("tool") == "get_policy"]
            if pol_evidence:
                st.json(pol_evidence[0]["data"].get("policy", pol_evidence[0]["data"]))
            else:
                policy = load_policy()
                st.json(policy)
        else:
            policy = load_policy()
            st.warning(policy["notice"])
            st.json(policy)

    # ── Tab 3: Proposed party messages ──────────────────────────────────
    with tab_messages:
        m1, m2 = st.columns(2)
        with m1:
            st.markdown("""
            <div class="card" style="height:100%;">
                <div class="card-title">For the rider</div>
            """, unsafe_allow_html=True)
            st.write(ruling["rider_message"])
            st.markdown("</div>", unsafe_allow_html=True)
        with m2:
            st.markdown("""
            <div class="card" style="height:100%;">
                <div class="card-title">For the driver</div>
            """, unsafe_allow_html=True)
            st.write(ruling["driver_message"])
            st.markdown("</div>", unsafe_allow_html=True)
        st.caption("No payment is executed and no message is sent to either party.")

    # ── JSON download (secondary control) ───────────────────────────────
    with st.expander("Download case report (JSON)"):
        st.download_button(
            "Download report",
            data=json.dumps(result, indent=2),
            file_name=f'{selected_id}_multi_agent_report.json',
            mime="application/json",
        )

elif result and result.get("trip_id") != selected_id:
    st.info(f"The displayed result is for case `{result['trip_id']}`. Select that case to view it again, or investigate the current case.")

else:
    with st.expander("Preview this trip's synthetic evidence"):
        st.json({k: v for k, v in case.items() if k not in {"complaint", "title"}})


# ── Footer ──────────────────────────────────────────────────────────────
st.markdown("<div style='margin-top:2rem;'></div>", unsafe_allow_html=True)
st.markdown("""
<div style="border-top:1px solid #e2e8f0;padding-top:1rem;display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:0.75rem;color:#64748b;font-size:0.75rem;">
    <div>
        <div style="font-weight:600;color:#1a3c34;margin-bottom:0.2rem;">Built for fair resolutions. Designed for human oversight.</div>
        <div>Original prototype reference · Synthetic demonstration · Recommendations only · No payment is executed.</div>
    </div>
    <div style="text-align:right;">
        <div class="badge badge-grey">Prototype · Recommendations only</div>
    </div>
</div>
""", unsafe_allow_html=True)
