"""Streamlit app — Ride Dispute Review.

Run with: python -m streamlit run app.py

The only user-facing mode is ADP multi-agent: one request goes to the
published Tencent ADP application, which routes among Rider Advocate,
Driver Advocate and Judge agents internally. The backend validates the
Judge's final ruling against the demo policy and evidence IDs.
"""
import copy
import json
import math
import uuid
import inspect
import html
from pathlib import Path

import streamlit as st

from disputes.adp import ADPClient, ADPError, settings
from disputes.core import (
    OutputError, build_evidence_timeline, load_cases, load_policy,
    money, resolve, save_result,
)
from human_review_store import (save_review, get_review_for_run, get_review_by_id,
                                charged_cents_for, model_confidence_for, _to_cents)

ROOT = Path(__file__).resolve().parent

PRIMARY_GREEN = "#0d7a5e"
DARK_GREEN = "#1a3c34"
MINT_BG = "#f7faf8"
MINT_CARD = "#e8f5f0"
WHITE = "#ffffff"
BORDER = "#dce8e2"
MUTED = "#64748b"
TEXT = "#1f2937"


def _html(markup: str):
    st.markdown("\n".join(line.lstrip() for line in markup.splitlines()), unsafe_allow_html=True)


def _css():
    _html(f"""
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
        background: #eaf5ef !important;
    }}
    [data-testid="stSidebar"] > div:first-child {{
        background: #eaf5ef;
    }}

    /* Hide only the Streamlit main-menu (hamburger); keep the header and
       its native sidebar collapse/expand toggle visible and clickable. */
    #MainMenu {{visibility: hidden;}}

    /* Buttons */
    .stButton > button {{
        border-radius: 8px;
        font-weight: 500;
        transition: all 0.15s ease;
    }}
    [data-testid="stBaseButton-primary"] {{
        background: {PRIMARY_GREEN};
        border: 1px solid {PRIMARY_GREEN};
        color: white;
    }}
    [data-testid="stBaseButton-primary"]:hover {{
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
        gap: 0.4rem;
        padding: 0.3rem 0.65rem;
        border-radius: 999px;
        font-size: 0.75rem;
        font-weight: 600;
        white-space: nowrap;
    }}
    .badge-lg {{
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
        padding: 0.75rem 1.25rem;
        border-radius: 999px;
        font-size: 1rem;
        font-weight: 600;
        white-space: normal; text-align:center;
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
    .badge-red {{
        background: #fef2f2;
        color: #b91c1c;
        border: 1px solid #fecaca;
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

    /* Narrow screens: shrink badge text to avoid overlap with breadcrumb */
    @media (max-width: 768px) {{
        .badge, .badge-lg {{
            font-size: 0.95rem;
            padding: 0.5rem 0.9rem;
        }}
    }}
    [data-testid="stForm"] {{ background: {WHITE}; border: 1px solid {BORDER}; border-radius:16px; padding:1.25rem; }}
    [data-testid="stHeader"] {{ background:rgba(247,250,248,.96); }}
    .st-key-why_card, .st-key-rider_message, .st-key-driver_message {{ background:{WHITE}; border-radius:14px; }}
    .agent-card {{ border-top:3px solid #abd2bf; box-shadow:0 3px 12px rgba(26,60,52,.035); }}
    [data-testid="stExpander"] {{ background:{WHITE}; border-radius:12px; }}
    [role="dialog"] {{ background:#f7faf8; }}
    .resolution-grid {{ display:grid; grid-template-columns:1.2fr 1fr 1fr; gap:1.5rem; }}
    @media(max-width:760px) {{
      .resolution-grid {{ grid-template-columns:1fr; gap:1rem; }}
      .resolution-grid > div {{ border-right:0 !important; padding-right:0 !important; }}
    }}
    </style>
    """)


# ── Page config ─────────────────────────────────────────────────────────
st.set_page_config(page_title="Ride Dispute Review", page_icon="⚖", layout="wide")
_css()

# ── Data load ───────────────────────────────────────────────────────────
cases = load_cases()
case_map = {c["trip_id"]: c for c in cases}

# User-facing dropdown allowlist, in the requested display order.
DROPDOWN_CASE_IDS = ["NS01", "NS02", "NS03", "NS04", "RT01", "RT02",
                     "DISP-001", "DISP-003"]

# Session-state initialisation.
if "selected_case" not in st.session_state:
    st.session_state["selected_case"] = DROPDOWN_CASE_IDS[0]
if "executing" not in st.session_state:
    st.session_state["executing"] = False
# Per-case investigation status: ready | investigating | completed | failed.
if "status_by_case" not in st.session_state:
    st.session_state["status_by_case"] = {}

# A saved review link restores this exact investigation after a browser refresh.
if not st.session_state.get("result") and st.query_params.get("review"):
    try:
        restored = get_review_by_id(st.query_params["review"])
        if restored and restored["case_id"] in DROPDOWN_CASE_IDS and restored["case_id"] == st.query_params.get("case"):
            snapshot = restored["ai_result"]
            if snapshot.get("trip_id") == restored["case_id"] and snapshot.get("run_id") == restored["run_id"]:
                st.session_state["selected_case"] = restored["case_id"]
                st.session_state["result"] = snapshot
    except RuntimeError as exc:
        st.warning(str(exc))

# Safely handle a previously selected case that is now hidden from the
# dropdown (e.g. NS05 chosen in an earlier session). Fall back to the
# first case in the allowlist.
selected_id = st.session_state["selected_case"]
if selected_id not in DROPDOWN_CASE_IDS:
    selected_id = DROPDOWN_CASE_IDS[0]
    st.session_state["selected_case"] = selected_id
case = copy.deepcopy(case_map[selected_id])


def _format_category(cat: str) -> str:
    return cat.replace("_", " ").title()


def _display_confidence(conf, colour: str = DARK_GREEN) -> str:
    """Return an HTML span for a confidence value, or 'Not available'."""
    if type(conf) in (int, float) and math.isfinite(conf) and 0 <= conf <= 1:
        return (f'<div class="metric-value" style="color:{colour};">'
                f'{conf:.0%}</div>')
    return f'<div class="metric-value" style="color:{colour};">Not available</div>'


def _escape_md(text: str) -> str:
    """Escape markdown special characters in untrusted text so it renders
    as literal content, not formatting or raw HTML."""
    if not text:
        return ""
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("`", "\\`")
    )


import re as _re

def _highlight_html(text: str) -> str:
    """Render public text as escaped HTML, with limited bold emphasis only.

    Dollar signs stay literal: this output must be passed to st.html, never
    Markdown's math parser. Model-provided HTML cannot become executable markup.
    """
    escaped = html.escape(str(text))
    pattern = r'(S?\$\d[\d,]*(?:\.\d{1,2})?|\b\d+(?:\.\d+)?\s*(?:kilometers|kilometres|meters|metres|minutes|seconds|km|min|sec|m)\b|DEMO-[A-Z]+-\d+|ORG-V2\.1-\d+\.\d+)'
    parts = _re.split(r'(\*\*.+?\*\*)', escaped, flags=_re.DOTALL)
    rendered = []
    for part in parts:
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            rendered.append("<strong>" + part[2:-2] + "</strong>")
        else:
            rendered.append(_re.sub(pattern, r'<strong>\1</strong>', part))
    return "".join(rendered).replace("\n", "<br>")


def _public_explanation(text: str, *, urgent: bool = False):
    colour = "#991b1b" if urgent else TEXT
    st.html('<div class="public-explanation" style="color:' + colour +
            ';font-family:inherit;font-size:1rem;line-height:1.65;white-space:normal;'
            'overflow-wrap:anywhere;word-break:normal;max-width:100%;">' +
            _highlight_html(text) + '</div>')


# ── Human-review workflow helpers ────────────────────────────────────────

def _validate_review_form(
    reviewer_id: str, human_decision: str, refund_amount: str,
    rider_message: str, driver_message: str, final_explanation: str,
    ai_result: dict,
) -> list[str]:
    """Validate the human-review form fields. Returns a list of error strings."""
    errors = []
    if human_decision not in {"refund", "no_action", "further_review"}:
        errors.append("Select a human decision.")
    if not reviewer_id or not reviewer_id.strip():
        errors.append("Reviewer name is required.")
    if not rider_message or not rider_message.strip():
        errors.append("Proposed message to the rider is required.")
    if not driver_message or not driver_message.strip():
        errors.append("Proposed message to the driver is required.")
    if not final_explanation or not final_explanation.strip():
        errors.append("Final decision explanation is required.")

    if human_decision == "refund":
        if not refund_amount or not refund_amount.strip():
            errors.append("Refund amount is required for a refund decision.")
        else:
            try:
                cents = _to_cents(refund_amount)
                if cents is None:
                    errors.append("Refund amount is required for a refund decision.")
                else:
                    charged = charged_cents_for(ai_result)
                    if charged is None:
                        errors.append(
                            "The charged amount is unknown; cannot accept a final refund amount."
                        )
                    elif cents > int(charged):
                        errors.append(
                            f"Refund cannot exceed the charged amount (S${int(charged) / 100:.2f})."
                        )
            except ValueError as exc:
                errors.append(str(exc))
    else:
        if refund_amount and refund_amount.strip():
            errors.append(
                "No action and further review must not contain a refund award."
            )
    return errors


def _render_human_review_card(result: dict, ruling: dict, selected_id: str):
    """Render the human-review resolution card and review workflow.

    Called when the AI outcome is human_review.  Checks persistent storage
    for an existing review record for this case+run.  If found, renders the
    post-submission card.  Otherwise, shows the review button.
    """
    run_id = result.get("run_id", "")
    _model_conf = model_confidence_for(result)
    _model_ruling = ruling.get("original_ruling")
    _esc_reason = ruling.get("escalation_reason")
    policy_version = result.get("policy_version", "")

    # Check for an existing saved review for this exact case+run.
    saved_review = st.session_state.get("_current_review")
    storage_error = st.session_state.get("_review_storage_error")

    if saved_review:
        _render_saved_review_card(saved_review, result, ruling, selected_id)
        if saved_review["human_decision"] != "further_review":
            return
        # Continuing a pending review appends a linked record to the same run.
        st.caption("This review remains pending. Add a final decision when the missing evidence is available.")

    if not saved_review:
        # --- No saved review yet: show the pending card + review button -------
        _esc_detail_html = ""
        original = result.get("original_ai_ruling", {})
        if original.get("ruling") == "human_review":
            _esc_detail_html = _highlight_html(original.get("rationale") or ruling["rationale"])
        elif _model_ruling is not None:
            _esc_detail_html = (
                "The model recommendation conflicts with the policy check. "
                "The result is pending human review; no refund is authorised. "
                + _highlight_html(_esc_reason or "")
            )
        else:
            _esc_detail_html = _highlight_html(_esc_reason or ruling.get("rationale", ""))

        _html(f"""
        <div class="card" style="background:#fef2f2;border:2px solid #b91c1c;">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:1rem;">
                <div style="display:flex;align-items:center;gap:0.5rem;">
                    <span style="font-size:1rem;">🛡</span>
                    <span style="font-weight:600;color:#7f1d1d;font-size:0.9rem;">Resolution recommendation</span>
                </div>
                <span style="display:inline-flex;align-items:center;gap:0.35rem;padding:0.35rem 0.85rem;border-radius:999px;background:#b91c1c;color:#ffffff;font-weight:700;font-size:0.8rem;">⚠ Human review required</span>
            </div>
            <div class="resolution-grid">
                <div style="border-right:1px solid #fecaca;padding-right:1rem;">
                    <div class="metric-label" style="color:#7f1d1d;">Recommended outcome</div>
                    <div class="metric-value" style="display:flex;align-items:center;gap:0.5rem;color:#7f1d1d;">
                        <span style="width:28px;height:28px;border-radius:50%;background:#b91c1c;color:white;display:inline-flex;align-items:center;justify-content:center;font-size:0.9rem;">!</span>
                        Human review required
                    </div>
                    <div class="metric-sub" style="color:#991b1b;">{policy_version}</div>
                </div>
                <div style="border-right:1px solid #fecaca;padding-right:1rem;">
                    <div class="metric-label" style="color:#7f1d1d;">Refund decision</div>
                    <div class="metric-value" style="color:#7f1d1d;">Pending human review</div>
                    <div class="metric-sub" style="color:#991b1b;">No refund executed</div>
                </div>
                <div>
                    <div class="metric-label" style="color:#7f1d1d;">Model confidence</div>
                    {_display_confidence(_model_conf, "#b91c1c")}
                    <div class="metric-sub" style="color:#991b1b;">Uncalibrated model estimate</div>
                </div>
            </div>
            <div style="margin-top:0.75rem;padding-top:0.75rem;border-top:1px solid #fecaca;color:#7f1d1d;font-size:0.85rem;line-height:1.5;">
                {_esc_detail_html}
            </div>
            <div style="margin-top:0.5rem;padding-top:0.5rem;border-top:1px solid #fecaca;">
                <span class="muted" style="font-size:0.75rem;color:#991b1b;">Recommendation only. Confidence is a prototype heuristic, not calibrated accuracy. · Policy: {policy_version} · Measured run time: {result.get('elapsed_seconds', 0):.3f}s</span>
            </div>
        </div>
        """)

    if storage_error:
        st.warning(storage_error + " The AI recommendation is still shown; no human decision has been saved.")
        return
    # Review button inside the card area.
    st.markdown("")
    _dialog_label = f"review_dialog_{selected_id}_{run_id}"

    if st.button("📝 Review case", key=f"review_btn_{selected_id}_{run_id}",
                 type="secondary", use_container_width=False):
        st.session_state["review_form_open"] = _dialog_label
        st.rerun()

    _render_review_dialog(result, ruling, selected_id, run_id)


def _render_review_dialog(result: dict, ruling: dict, selected_id: str, run_id: str):
    """Render the review form in an st.dialog (if supported) or expander."""
    _dialog_key = f"review_dialog_{selected_id}_{run_id}"
    _is_open = st.session_state.get("review_form_open") == _dialog_key

    # Determine charged amount for the refund cap display.
    _charged = charged_cents_for(result)

    _context_block = f"""
    **Case ID:** {selected_id}  
    **Investigation/Run ID:** {run_id}  
    **Complaint:** {_escape_md(result.get('complaint', 'N/A'))}  
    **Original AI recommendation:** {ruling.get('original_ruling') or ruling.get('ruling', 'N/A')}  
    **Model confidence:** {_format_confidence_text(model_confidence_for(result))}  
    **Escalation reason:** {ruling.get('escalation_reason') or 'N/A'}  
    **Policy version:** {result.get('policy_version', 'N/A')}
    """
    if _charged is not None:
        _context_block += f"\n**Charged amount:** {money(int(_charged))}"

    # Try st.dialog (available in Streamlit >= 1.35).
    _use_dialog = hasattr(st, "dialog")

    if _use_dialog:
        # Always define and call the dialog; it only shows when the user
        # has clicked "Review case" (which sets review_form_open).
        if _is_open:
            dialog_options = {"width": "large"}
            if "on_dismiss" in inspect.signature(st.dialog).parameters:
                def dismiss_review():
                    st.session_state.pop("review_form_open", None)
                dialog_options["on_dismiss"] = dismiss_review
            @st.dialog("Human review — demonstration workflow", **dialog_options)
            def _review_dialog_inner():
                _render_review_form_body(
                    result, ruling, selected_id, run_id, _context_block, _charged
                )
            _review_dialog_inner()
    else:
        # Fallback: expandable form.
        _expander_label = "📝 Human review — demonstration workflow"
        with st.expander(_expander_label, expanded=_is_open):
            _render_review_form_body(
                result, ruling, selected_id, run_id, _context_block, _charged
            )


def _format_confidence_text(conf) -> str:
    if type(conf) in (int, float) and math.isfinite(conf) and 0 <= conf <= 1:
        return f"{conf:.0%}"
    return "Not available"


def _render_review_form_body(
    result: dict, ruling: dict, selected_id: str, run_id: str,
    context_block: str, charged_cents,
):
    """Render the actual review form fields and handle submission."""
    st.caption("⚠ Demonstration reviewer workflow. A typed reviewer name is not "
               "authentication and must not be presented as verified staff identity.")
    st.markdown("---")
    st.markdown(context_block)
    st.markdown("---")

    human_decision = st.selectbox(
        "Human decision *",
        options=["", "refund", "no_action", "further_review"],
        format_func=lambda x: {
            "": "— Select —",
            "refund": "Refund",
            "no_action": "No action",
            "further_review": "Further review required",
        }.get(x, x),
        key=f"review_decision_{selected_id}_{run_id}",
    )

    # Use a form to prevent rerun on each keystroke, and to preserve
    # entered values if validation fails.
    with st.form(f"review_form_{selected_id}_{run_id}", clear_on_submit=False):
        reviewer_id = st.text_input(
            "Reviewer name or demo identifier *",
            key=f"reviewer_id_{selected_id}_{run_id}",
            placeholder="e.g. reviewer-alice",
        )
        refund_amount = st.text_input(
            "Refund amount (S$) — required for Refund only",
            key=f"refund_amount_{selected_id}_{run_id}",
            placeholder="e.g. 5.00",
            disabled=human_decision != "refund",
            help=(f"Maximum: {money(charged_cents)}" if charged_cents is not None else "Charged amount unknown: refund cannot be finalised."),
        )
        if human_decision != "refund":
            refund_amount = ""

        rider_msg = st.text_area(
            "Proposed message to the rider *",
            key=f"rider_msg_{selected_id}_{run_id}",
            height=80,
        )
        driver_msg = st.text_area(
            "Proposed message to the driver *",
            key=f"driver_msg_{selected_id}_{run_id}",
            height=80,
        )
        final_explanation = st.text_area(
            "Final decision explanation *",
            key=f"final_expl_{selected_id}_{run_id}",
            height=100,
        )

        col_save, col_cancel = st.columns(2)
        with col_save:
            submitted = st.form_submit_button("Save human review", type="primary")
        with col_cancel:
            cancelled = st.form_submit_button("Cancel", type="secondary")

    if cancelled:
        st.session_state.pop("review_form_open", None)
        st.rerun()

    if submitted:
        errors = _validate_review_form(
            reviewer_id, human_decision, refund_amount,
            rider_msg, driver_msg, final_explanation, result,
        )
        if errors:
            for e in errors:
                st.error(e)
            st.caption("Please correct the errors above and resubmit. "
                       "Your entered values are preserved.")
            return

        # Persist the review record.
        try:
            saved = save_review(
                case_id=selected_id,
                run_id=run_id,
                ai_result=result,
                original_confidence=model_confidence_for(result),
                escalation_reason=ruling.get("escalation_reason"),
                reviewer_id=reviewer_id.strip(),
                human_decision=human_decision,
                refund_amount_str=refund_amount if human_decision == "refund" else None,
                rider_message=rider_msg.strip(),
                driver_message=driver_msg.strip(),
                final_explanation=final_explanation.strip(),
                policy_version=result.get("policy_version", ""),
                linked_review_id=(st.session_state.get("_current_review") or {}).get("review_id"),
                submission_id=st.session_state.setdefault(
                    f"review_submission_{selected_id}_{run_id}_" + str((st.session_state.get("_current_review") or {}).get("review_id")),
                    str(uuid.uuid4())),
            )
            st.session_state.pop("review_form_open", None)
            st.session_state["last_saved_review"] = saved
            st.query_params["review"] = saved["review_id"]
            st.query_params["case"] = selected_id
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
            st.caption("Your entered values are preserved. Correct the error and resubmit.")
        except RuntimeError as exc:
            st.error(f"Storage failed: {exc}")
            st.caption("The review was not saved. Your entered values are preserved. "
                       "Check the database connection and try again.")


def _render_saved_review_card(review: dict, ai_result: dict, ruling: dict, selected_id: str):
    """Render the post-submission card after a human review is saved."""
    decision = review["human_decision"]
    is_final = decision in ("refund", "no_action")
    is_further = decision == "further_review"

    if is_final:
        # Green card for a completed human decision.
        _refund_text = money(review["refund_cents"]) if review["refund_cents"] > 0 \
            else "No refund recommended"
        _badge = (
            '<span style="display:inline-flex;align-items:center;gap:0.35rem;'
            'padding:0.35rem 0.85rem;border-radius:999px;background:#0d7a5e;'
            'color:#ffffff;font-weight:700;font-size:0.8rem;">'
            '✓ Human review completed</span>'
        )
        _bg = MINT_CARD
        _border = "#c5e8dc"
        _heading_color = DARK_GREEN
        _metric_color = DARK_GREEN
        _sub_color = MUTED
        _icon_bg = PRIMARY_GREEN
        _icon = "✓"
        _outcome_text = "Human review: " + ("Refund" if decision == "refund" else "No action")
    else:
        # Amber/red card for further review required.
        _refund_text = "Pending further review"
        _badge = (
            '<span style="display:inline-flex;align-items:center;gap:0.35rem;'
            'padding:0.35rem 0.85rem;border-radius:999px;background:#b45309;'
            'color:#ffffff;font-weight:700;font-size:0.8rem;">'
            '⚠ Further human review required</span>'
        )
        _bg = "#fffbeb"
        _border = "#fde68a"
        _heading_color = "#92400e"
        _metric_color = "#92400e"
        _sub_color = "#a16207"
        _icon_bg = "#b45309"
        _icon = "!"
        _outcome_text = "Further review required"

    _conf_html = '<div class="metric-value" style="color:' + _metric_color + ';">—</div>'

    _html(f"""
    <div class="card" style="background:{_bg};border:2px solid {_border};">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:1rem;">
            <div style="display:flex;align-items:center;gap:0.5rem;">
                <span style="font-size:1rem;">🛡</span>
                <span style="font-weight:600;color:{_heading_color};font-size:0.9rem;">Resolution recommendation</span>
            </div>
            {_badge}
        </div>
        <div class="resolution-grid">
            <div style="border-right:1px solid {_border};padding-right:1rem;">
                <div class="metric-label" style="color:{_sub_color};">Recommended outcome</div>
                <div class="metric-value" style="display:flex;align-items:center;gap:0.5rem;color:{_metric_color};">
                    <span style="width:28px;height:28px;border-radius:50%;background:{_icon_bg};color:white;display:inline-flex;align-items:center;justify-content:center;font-size:0.9rem;">{_icon}</span>
                    {_outcome_text}
                </div>
                <div class="metric-sub" style="color:{_sub_color};">{review.get('policy_version', '')}</div>
            </div>
            <div style="border-right:1px solid {_border};padding-right:1rem;">
                <div class="metric-label" style="color:{_sub_color};">Refund</div>
                <div class="metric-value" style="color:{_metric_color};">{_refund_text}</div>
                <div class="metric-sub" style="color:{_sub_color};">Human decision — not a payment</div>
            </div>
            <div>
                <div class="metric-label" style="color:{_sub_color};">Confidence</div>
                {_conf_html}
                <div class="metric-sub" style="color:{_sub_color};">Not applicable — human decision</div>
            </div>
        </div>
        <div style="margin-top:0.75rem;padding-top:0.75rem;border-top:1px solid {_border};color:{_heading_color};font-size:0.85rem;line-height:1.5;">
            <strong>Reviewer:</strong> {_escape_md(review.get('reviewer_id', ''))} ·
            <strong>Reviewed at:</strong> {_escape_md(review.get('created_at', ''))}
        </div>
        <div style="margin-top:0.5rem;color:{_heading_color};font-size:0.85rem;line-height:1.5;">
            <strong>Explanation:</strong> {_escape_md(review.get('final_explanation', ''))}
        </div>
        <div style="margin-top:0.5rem;padding-top:0.5rem;border-top:1px solid {_border};">
            <span class="muted" style="font-size:0.75rem;color:{_sub_color};">
                {("Human review completed and recorded." if is_final else "Further review remains pending.")} No refund has been paid and no message has been sent.
            </span>
        </div>
    </div>
    """)

    _pm1, _pm2 = st.columns(2)
    with _pm1, st.container(border=True, key="rider_message"):
        st.markdown("**Proposed message to the rider**")
        st.text(review.get("rider_message", ""))
    with _pm2, st.container(border=True, key="driver_message"):
        st.markdown("**Proposed message to the driver**")
        st.text(review.get("driver_message", ""))

    # Collapsed original AI review section.
    _html("<div style='margin-top:0.75rem;'></div>")
    with st.expander("Original AI review", expanded=False):
        _ai_conf = model_confidence_for(ai_result)
        st.write(f"**AI recommendation:** {ruling.get('original_ruling') or ruling.get('ruling', 'N/A')}")
        st.write(f"**Model confidence:** {_format_confidence_text(_ai_conf)}")
        st.write(f"**Escalation reason:** {ruling.get('escalation_reason') or 'N/A'}")
        st.write(f"**Policy version:** {ai_result.get('policy_version', 'N/A')}")
        st.write(f"**AI rationale:** {ruling.get('rationale', 'N/A')}")
        st.json(ai_result)

    # JSON download of the review record.
    _html("<div style='margin-top:0.75rem;'></div>")
    with st.expander("Download human review record (JSON)"):
        st.download_button(
            "Download review record",
            data=json.dumps(review, indent=2, default=str),
            file_name=f'{selected_id}_human_review_{review.get("review_id", "unknown")[:8]}.json',
            mime="application/json",
        )


# ── Sidebar ─────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("**Case Queue**")

    def _select_label(key: str) -> str:
        c = case_map[key]
        return f"{c['trip_id']} — {c['title']}"

    selected = st.selectbox(
        "Select a case",
        options=DROPDOWN_CASE_IDS,
        format_func=_select_label,
        index=DROPDOWN_CASE_IDS.index(selected_id),
        key="case_select",
    )

    if selected != st.session_state["selected_case"]:
        if st.session_state.get("result"):
            st.session_state.setdefault("results_by_case", {})[st.session_state["selected_case"]] = st.session_state["result"]
        st.session_state["selected_case"] = selected
        st.query_params.clear()
        st.session_state.pop("result", None)
        cached = st.session_state.get("results_by_case", {}).get(selected)
        if cached:
            st.session_state["result"] = cached
        st.session_state.pop("review_form_open", None)
        st.session_state.pop("adp_debug", None)
        st.session_state.pop("validation_debug", None)
        # New case shows "Ready" unless it already has a completed result.
        if st.session_state["status_by_case"].get(selected) == "investigating":
            st.session_state["status_by_case"][selected] = "ready"
        st.rerun()

    # ── Selected-case summary ──────────────────────────────────────────
    _sc = case_map[selected_id]
    _pay = _sc.get("payment", {})
    _trip = _sc.get("trip", {})
    _is_org = _sc.get("policy_version") == "organiser-v2.1"

    # Determine monetary values honestly.
    _charged = _pay.get("charged_cents")
    _cancel_fee = _pay.get("cancellation_fee_cents")
    _ref_fare = _pay.get("reference_fare_cents")

    if _cancel_fee and _cancel_fee > 0:
        _fare_label = "Cancellation fee"
        _fare_val = money(_cancel_fee)
    elif _charged is not None:
        _fare_label = "Charged fare"
        _fare_val = money(_charged)
    else:
        _fare_label = "Charged fare"
        _fare_val = "Unknown"

    if _ref_fare is not None and _ref_fare > 0:
        _ref_val = money(_ref_fare)
    else:
        _ref_val = "Not supplied"

    # Short description: use an existing description field if available,
    # otherwise a truncated excerpt of the complaint (no AI call).
    _desc = _sc.get("description") or _sc.get("source") or ""
    if not _desc:
        _raw_complaint = _sc.get("complaint", "")
        _desc = (_raw_complaint[:120] + "…") if len(_raw_complaint) > 120 else _raw_complaint

    _source_label = "Organiser-provided" if _is_org else "Synthetic demo"

    st.markdown("---")
    st.caption(f"Selected case · {_sc['trip_id']}")
    st.markdown(f"**{_sc['title']}**")
    st.caption(_format_category(_sc["category"]))
    st.caption(_desc)
    st.markdown("")
    _s1, _s2 = st.columns(2)
    with _s1:
        st.caption(_fare_label)
        st.markdown(f"**{_fare_val}**")
    with _s2:
        st.caption("Reference fare")
        st.markdown(f"**{_ref_val}**")
    st.caption(f"Dataset: {_source_label}")


# ── Top bar ─────────────────────────────────────────────────────────────
result = st.session_state.get("result")
_status_map = st.session_state.get("status_by_case", {})
# Derive the effective status: completed only when the stored result is
# valid and belongs to the selected case; failed when validation or the
# request errored; investigating during the request; otherwise ready.
if st.session_state.get("executing"):
    effective_status = "investigating"
elif _status_map.get(selected_id) == "failed":
    effective_status = "failed"
elif result and result.get("trip_id") == selected_id:
    effective_status = "completed"
else:
    effective_status = "ready"

_badge = {
    "ready": '<span class="badge-lg badge-grey">Ready to investigate</span>',
    "investigating": '<span class="badge-lg badge-amber">Investigating…</span>',
    "completed": '<span class="badge-lg badge-green"><span>✓</span> Investigation completed</span>',
    "failed": '<span class="badge-lg badge-red">Investigation failed</span>',
}


def _badge_html(status: str) -> str:
    return f"""<div style="display:flex;justify-content:flex-end;align-items:flex-end;
    height:100%;padding-bottom:0.35rem;">{_badge[status]}</div>"""


_html(f"""
<div class="top-bar">
    <div style="display:flex;align-items:center;gap:0.5rem;font-size:0.85rem;color:#64748b;">
        <span>Disputes</span>
        <span style="color:#cbd5e1;">/</span>
        <span style="font-weight:600;color:#1a3c34;">Case {selected_id}</span>
    </div>
</div>
""")


# ── Page heading ────────────────────────────────────────────────────────
head_col1, head_col2 = st.columns([3, 2])
with head_col1:
    _html('<div class="eyebrow">Evidence-led resolution</div>')
    _html('<h1 class="page-title">Ride Dispute Review</h1>')
    _html('<div class="page-subtitle">Three specialised AI agents. Every perspective considered.</div>')
# Updateable placeholder so the badge can switch to "Investigating…" before
# the blocking network request begins, without a full page rerun.
status_placeholder = head_col2.empty()
status_placeholder.markdown(_badge_html(effective_status), unsafe_allow_html=True)

_html("<div style='margin-bottom:1.25rem;'></div>")


# ── Complaint card ─────────────────────────────────────────────────────-
with st.form("complaint_form"):
    _html(f"""
    <div>
        <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.35rem;">
            <span class="queue-id">{selected_id} · {_format_category(case['category'])}</span>
            <span class="badge badge-grey" style="margin-left:auto;">Rider-submitted dispute</span>
        </div>
        <div class="card-title" style="font-size:1.15rem;margin-bottom:0.75rem;">{case['title']}</div>
        <div style="background:#f8fafb;border:1px solid {BORDER};border-radius:10px;padding:0.9rem 1rem;margin-bottom:1rem;">
            <div style="display:flex;align-items:center;gap:0.4rem;color:#64748b;font-size:0.75rem;font-weight:600;margin-bottom:0.4rem;text-transform:uppercase;letter-spacing:0.04em;">
                <span style="font-size:0.9rem;">❝</span> Rider's complaint
            </div>
        </div>
    </div>
    """)

    complaint = st.text_area(
        "Rider's complaint",
        value=case["complaint"],
        max_chars=2000,
        key=f"complaint_{selected_id}",
        label_visibility="collapsed",
        height=90,
    )

    c1, c2 = st.columns([4, 1])
    with c2:
        submitted = st.form_submit_button(
            "⚡ Investigate dispute", type="primary", use_container_width=True,
            disabled=st.session_state.get("executing", False),
        )


# ── Investigation handling (behaviour preserved) ────────────────────────
if submitted and not st.session_state["executing"]:
    st.query_params.clear()
    st.session_state.get("results_by_case", {}).pop(selected_id, None)
    st.session_state.pop("review_form_open", None)
    st.session_state["executing"] = True
    st.session_state.pop("result", None)
    st.session_state.pop("adp_debug", None)
    st.session_state.pop("validation_debug", None)
    # Mark investigating for this case so the badge shows yellow during the
    # request, before the response returns.
    st.session_state["status_by_case"][selected_id] = "investigating"
    # Render the yellow badge IMMEDIATELY, before evidence loading or the
    # blocking network request begins. This updates the placeholder created
    # above in the page heading area.
    status_placeholder.markdown(_badge_html("investigating"), unsafe_allow_html=True)
    case["complaint"] = complaint.strip()
    if not case["complaint"]:
        st.session_state["status_by_case"][selected_id] = "ready"
        st.warning("Enter a complaint before investigating.")
        status_placeholder.markdown(_badge_html("ready"), unsafe_allow_html=True)
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
            st.session_state["status_by_case"][selected_id] = "completed"
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
            st.session_state["status_by_case"][selected_id] = "failed"
        except OutputError as exc:
            st.error("Schema validation failed: " + str(exc))
            st.caption("ADP returned a response but it did not pass the project's result validator. No fabricated fields were accepted.")
            val_debug = getattr(exc, "validation_debug", None)
            if val_debug:
                # Enrich with ADP debug metadata (MessageIds, completion status,
                # final reply text) so the diagnostic expander can show the
                # actual ruling value, selected MessageId and stream status.
                _adp_dbg = getattr(exc, "debug_info", None) or st.session_state.get("adp_debug")
                if _adp_dbg:
                    val_debug["adp_event_types"] = _adp_dbg.get("event_types", [])
                    val_debug["adp_message_ids"] = _adp_dbg.get("message_ids", [])
                    val_debug["adp_completion_status"] = _adp_dbg.get("completion_status", "N/A")
                    val_debug["adp_final_reply_text"] = _adp_dbg.get("final_reply_text", "")
                    val_debug["adp_activity_event_count"] = _adp_dbg.get("activity_event_count", 0)
                st.session_state["validation_debug"] = val_debug
            st.session_state["status_by_case"][selected_id] = "failed"
        except (ValueError, OSError) as exc:
            st.error("Unexpected error: " + str(exc))
            st.caption("No recommendation was accepted.")
            st.session_state["status_by_case"][selected_id] = "failed"
    st.session_state["executing"] = False
    status_placeholder.markdown(_badge_html(st.session_state["status_by_case"].get(selected_id, "ready")), unsafe_allow_html=True)


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
    with st.expander("Validation diagnostics — received output and schema check"):
        # Show the actual ruling value from the received JSON.
        _jr = val_debug.get("judge_ruling_json") or {}
        _actual_ruling = _jr.get("ruling", "(missing)")
        st.write(f"**Actual ruling value:** `{_actual_ruling}`")
        st.write(f"**Valid rulings:** `refund`, `no_action`, `human_review`")

        # Show ADP-side metadata (MessageIds, completion status, raw reply).
        if val_debug.get("adp_completion_status"):
            st.write(f"**Stream completion status:** `{val_debug['adp_completion_status']}`")
        if val_debug.get("adp_event_types"):
            st.write("**Event types received:**")
            st.text(", ".join(val_debug["adp_event_types"]))
        if val_debug.get("adp_message_ids"):
            st.write("**Messages by MessageId:**")
            st.dataframe(val_debug["adp_message_ids"], hide_index=True)

        # Show evidence and policy IDs side by side.
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
        st.json(_jr)

        _raw = val_debug.get("adp_final_reply_text", "")
        if _raw:
            st.write("**Raw reply text (as parsed from SSE):**")
            st.code(_raw[:5000], language="text")
            if len(_raw) > 5000:
                st.caption(f"Truncated — full text is {len(_raw)} characters.")
        st.caption("No credentials or private reasoning are exposed.")


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

    # Determine the real escalation reason from the trace, if any.
    _escalation_reason = None
    _trace = result.get("trace", [])
    for _entry in _trace:
        if _entry.get("event") == "review_required":
            _escalation_reason = _entry.get("detail", {}).get("reason")
            break

    # Resolution card
    _html("<div style='margin-top:1.25rem;'></div>")

    # Check if a saved human review exists for this case+run.
    _saved_hr = None
    st.session_state.pop("_review_storage_error", None)
    if human_review and result.get("run_id"):
        try:
            _saved_hr = get_review_for_run(selected_id, result["run_id"])
        except RuntimeError as exc:
            st.session_state["_review_storage_error"] = str(exc)
    st.session_state["_current_review"] = _saved_hr

    if human_review:
        # Delegate to the human-review workflow, which checks persistent
        # storage for an existing review and renders the appropriate card.
        _render_human_review_card(result, ruling, selected_id)

    else:
        # ── Normal (refund / no_action) branch: existing HTML card ────────
        _html(f"""
        <div class="card" style="background:{MINT_CARD};border-color:#c5e8dc;">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:1rem;">
                <div style="display:flex;align-items:center;gap:0.5rem;">
                    <span style="font-size:1rem;">🛡</span>
                    <span style="font-weight:600;color:#1a3c34;font-size:0.9rem;">Resolution recommendation</span>
                </div>
                <span class="badge badge-grey">AI recommendation</span>
            </div>
            <div class="resolution-grid">
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
        """)

    # Explanation + evidence cards
    _html("<div style='margin-top:1.25rem;'></div>")
    why_col, ev_col = st.columns([2, 1])

    with why_col:
        with st.container(border=True, key="why_card"):
            st.markdown("**Why this outcome?**")
            _rationale = _saved_hr["final_explanation"] if _saved_hr else (
                result.get("original_ai_ruling", {}).get("rationale", ruling["rationale"])
                if result.get("original_ai_ruling", {}).get("ruling") == "human_review"
                else ruling["rationale"])
            _public_explanation(_rationale, urgent=human_review and not _saved_hr)
            st.caption("Human reviewer explanation" if _saved_hr else "Based on the supplied evidence and policy")

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

        _html(f"""
        <div class="card" style="height:100%;">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:0.75rem;">
                <div style="display:flex;align-items:center;gap:0.5rem;">
                    <span style="font-size:1rem;">🧩</span>
                    <span class="card-title" style="margin:0;">Evidence at a glance</span>
                </div>
            </div>
            {ev_html}
        </div>
        """)

    # ── Tabs ────────────────────────────────────────────────────────────
    _html("<div style='margin-top:1.25rem;'></div>")
    tab_review, tab_evidence, tab_messages = st.tabs([
        "Agent review", "Evidence & policy", "Proposed party messages",
    ])

    # ── Tab 1: Agent review ─────────────────────────────────────────────
    with tab_review:
        _html("""
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:0.75rem;">
            <span class="muted">Different perspectives. One evidence-based recommendation.</span>
            <span class="badge badge-grey">Multi-agent review</span>
        </div>
        """)

        advocates = result.get("advocates", {})
        adp_activity = result.get("adp_activity", [])

        a1, a2, a3 = st.columns(3)
        with a1:
            _html("""
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
            """)
        with a2:
            _html("""
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
            """)
        with a3:
            judge_summary = _highlight_html(result.get("original_ai_ruling", {}).get("rationale", ruling["rationale"]))
            st.html(f"""
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
            """)

        _html("""
        <div style="margin-top:0.75rem;color:#64748b;font-size:0.8rem;line-height:1.4;">
            Individual advocate reports are not returned as separate structured outputs. The Judge's ruling summarises the competing arguments.
        </div>
        """)

        # Investigation activity (collapsible, collapsed by default)
        _html("<div style='margin-top:1.5rem;'></div>")
        with st.expander("Investigation activity", expanded=False):
            if adp_activity:
                for i, a in enumerate(adp_activity):
                    detail = a.get("detail", {})
                    agent = detail.get("agent", "")
                    typ = detail.get("type", "")
                    event_label = a.get("event", "").replace("_", " ").title()
                    title = f"{agent} {event_label}".strip() if agent else event_label
                    seq = a.get("sequence", i + 1)
                    parts = [f"**{title}**"]
                    if typ:
                        parts.append(f" · {typ}")
                    parts.append(f"  \nSequence {seq}")
                    st.markdown("".join(parts))
            else:
                st.caption("No activity metadata returned for this investigation.")
            st.caption("Readable labels for ADP stream events. No internal reasoning inferred.")

    # ── Tab 2: Evidence and policy ──────────────────────────────────────
    with tab_evidence:
        _html("""
        <div class="card" style="margin-bottom:1rem;">
            <div class="card-title">Python-calculated metrics</div>
        """)
        st.json(result["metrics"])
        _html("</div>")

        timeline = build_evidence_timeline(case)
        if timeline:
            _html("""
            <div class="card" style="margin-bottom:1rem;">
                <div class="card-title">Evidence timeline (Asia/Singapore time)</div>
                <div class="muted" style="margin-bottom:0.75rem;">Claims are text from chat messages; observations are GPS/telemetry events.</div>
            """)
            for entry in timeline:
                tag = "Claim" if entry["type"] == "claim" else "Observation"
                st.write(f'{entry["timestamp"]} — **{entry["label"]}** ({tag})')
                st.caption(entry["detail"])
            _html("</div>")
        else:
            st.info("No timestamped events are available for a timeline in this case.")

        _html('<div class="card-title">Evidence records</div>')
        for item in result["evidence"]:
            with st.expander(item["id"]):
                st.json(item)

        _html("<div style='margin-top:1rem;'></div>")
        _html(f'<div class="card-title">Policy ({result["policy_version"]})</div>')
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
        if _saved_hr:
            st.info("The human reviewer's proposed messages are shown above in the "
                    "resolution card. The original AI's proposed messages are preserved "
                    "in the collapsed 'Original AI review' section.")
        else:
            m1, m2 = st.columns(2)
            with m1, st.container(border=True):
                st.markdown("**For the rider**")
                st.text(ruling["rider_message"])
            with m2, st.container(border=True):
                st.markdown("**For the driver**")
                st.text(ruling["driver_message"])
            st.caption("No payment is executed and no message is sent to either party.")

    # ── JSON download (secondary control) ───────────────────────────────
    if not _saved_hr:
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
_html("<div style='margin-top:2rem;'></div>")
_html("""
<div style="border-top:1px solid #e2e8f0;padding-top:1rem;display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:0.75rem;color:#64748b;font-size:0.75rem;">
    <div>
        <div style="font-weight:600;color:#1a3c34;margin-bottom:0.2rem;">Built for fair resolutions. Designed for human oversight.</div>
        <div>Original prototype reference · Synthetic demonstration · Recommendations only · No payment is executed.</div>
    </div>
    <div style="text-align:right;">
        <div class="badge badge-grey">Prototype · Recommendations only</div>
    </div>
</div>
""")
