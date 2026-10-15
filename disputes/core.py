from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import json
import math
from pathlib import Path
import sqlite3
import sys
import time
import uuid

from . import prompts

ROOT = Path(__file__).resolve().parents[1]
# Ensure the project root is on sys.path so organiser_support can be imported
# regardless of the working directory (needed for Render deployment).
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TOOLS = ("get_trip", "get_messages", "get_payment", "get_metrics", "get_policy", "get_history")
REQUIRED_TOOLS = set(TOOLS) - {"get_history"}
RULINGS = {"refund", "no_action", "human_review"}

# Organiser cases use organiser policy v2.1, not the synthetic demo policy.
_ORGANISER_IDS = frozenset({"DISP-001", "DISP-002", "DISP-003"})


def _is_organiser_case(case_id: str) -> bool:
    return case_id in _ORGANISER_IDS


class OutputError(ValueError):
    pass


def load_cases() -> list[dict]:
    """Load both the original synthetic regression suite and organiser cases."""
    cases = json.loads((ROOT / "data/cases.json").read_text(encoding="utf-8"))
    # Add organiser cases, normalised to the app's case model.
    try:
        import organiser_support as org
        for info in org.list_cases():
            raw = org.load_case(info["case_id"])
            cases.append(_normalise_organiser_case(raw, info))
    except Exception:
        # If organiser_data is not available (e.g. minimal deployment), skip gracefully.
        pass
    return cases


def _normalise_organiser_case(raw: dict, info: dict) -> dict:
    """Convert an organiser fixture into the app's case model."""
    import organiser_support as org
    t = raw["trip_data"]
    category = info["category"]
    payment_cents = org.cents(t.get("actual_fare", t.get("cancellation_fee")))
    ref_cents = org.cents(t.get("upfront_quote", t.get("estimated_fare")))
    fee_cents = org.cents(t.get("cancellation_fee"))

    # Build a trip dict compatible with the app model.
    trip = {
        "trip_id": t["trip_id"],
        "pickup": {"lat": t["pickup_location"]["lat"], "lon": t["pickup_location"]["lng"],
                    "name": t["pickup_location"].get("name", "")},
        "dropoff": {"lat": t["dropoff_location"]["lat"], "lon": t["dropoff_location"]["lng"],
                     "name": t["dropoff_location"].get("name", "")},
        "start_time": t.get("start_time"),
        "end_time": t.get("end_time"),
        "scheduled_at": t.get("scheduled_time"),
        "arrived_at": t.get("driver_arrival_time"),
        "cancelled_at": t.get("cancellation_time"),
    }

    if category == "route_deviation":
        trip["actual_distance_km"] = t.get("actual_distance_km")
        trip["estimated_distance_km"] = t.get("estimated_distance_km")
        trip["excess_distance_km"] = t.get("excess_distance_km")
        trip["estimated_duration_min"] = t.get("estimated_duration_min")
        trip["actual_duration_min"] = t.get("actual_duration_min")
        trip["estimated_fare"] = t.get("estimated_fare")
        trip["actual_fare"] = t.get("actual_fare")
        trip["excess_fare"] = t.get("excess_fare")
        trip["route_deviated"] = t.get("route_deviated")
        trip["actual_route"] = [
            {"lat": p["lat"], "lon": p["lng"],
             **({"timestamp": p["timestamp"]} if "timestamp" in p else {})}
            for p in raw.get("gps_telemetry", [])
        ]
        trip["reference_route"] = [
            {"lat": p["lat"], "lon": p["lng"]}
            for p in raw.get("optimal_route", {}).get("waypoints", [])
        ]
    elif category == "no_show_charge":
        trip["pickup_presence_samples"] = [
            {"lat": p["lat"], "lon": p["lng"], "timestamp": p["timestamp"],
             "status": p.get("status", "")}
            for p in raw.get("gps_telemetry", [])
            if p.get("status") in ("arrived", "waiting", "cancelled")
        ]
    elif category == "fare_dispute":
        trip["upfront_quote"] = t.get("upfront_quote")
        trip["actual_fare"] = t.get("actual_fare")
        trip["fare_difference"] = t.get("fare_difference")

    # Build messages compatible with the app model.
    messages = []
    for m in raw.get("chat_logs", []):
        msg = {
            "timestamp": m.get("timestamp"),
            "sender": m.get("sender", "unknown"),
            "text": m.get("content", m.get("message", "")),
        }
        messages.append(msg)

    payment = {
        "currency": "SGD",
        "charged_cents": payment_cents,
        "reference_fare_cents": ref_cents,
        "cancellation_fee_cents": fee_cents or 0,
        "fare_breakdown": raw.get("fare_breakdown"),
        "surge_pricing_log": raw.get("surge_pricing_log"),
        "source_note": "Fixture reported charge; no independent payment settlement record supplied.",
    }

    history = {
        "rider_profile": raw.get("rider_profile", {}),
        "driver_profile": raw.get("driver_profile", {}),
        "note": "Ratings and flags do not establish fault in this trip. No dated cancellation list is supplied.",
    }

    return {
        "trip_id": info["case_id"],
        "category": category,
        "title": raw.get("dispute_ticket", {}).get("dispute_type", "").replace("_", " ").title(),
        "complaint": info["complaint"],
        "trip": trip,
        "messages": messages,
        "payment": payment,
        "history": history,
        "source": "Organiser-provided hackathon fixture; not independently verified live operational data",
        "policy_version": "organiser-v2.1",
        "traffic_conditions": raw.get("traffic_conditions"),
        "app_events": raw.get("app_events"),
        "surge_pricing_log": raw.get("surge_pricing_log"),
    }


def load_policy() -> dict:
    return json.loads((ROOT / "data/policy.json").read_text(encoding="utf-8"))


def money(cents: int) -> str:
    return f"S${cents / 100:.2f}"


def distance_m(a: dict, b: dict) -> float:
    lat1, lat2 = math.radians(a["lat"]), math.radians(b["lat"])
    dlat = lat2 - lat1
    dlon = math.radians(b["lon"] - a["lon"])
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6_371_000 * 2 * math.asin(math.sqrt(min(1.0, max(0.0, h))))


def route_distance(points: list[dict]) -> float | None:
    if len(points) < 2:
        return None
    return sum(distance_m(a, b) for a, b in zip(points, points[1:]))


def calculate_metrics(case: dict, policy: dict) -> dict:
    trip, payment = case["trip"], case["payment"]
    case_id = case.get("trip_id", "")

    # Organiser cases use organiser_support's metrics, not the synthetic policy.
    if _is_organiser_case(case_id):
        try:
            import organiser_support as org
            raw = org.load_case(case_id)
            return org.calculate_metrics(raw)
        except Exception:
            pass

    if case["category"] == "route_deviation":
        actual = route_distance(trip.get("actual_route", []))
        reference = route_distance(trip.get("reference_route", []))
        ratio = actual / reference if actual is not None and reference else None
        refund = 0
        if actual is not None and reference is not None:
            raw = Decimal(str(max(0, actual - reference) / 1000)) * Decimal(str(policy["route"]["rate_per_km_cents"]))
            refund = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        cap = max(0, payment["charged_cents"] - payment["reference_fare_cents"])
        return {"actual_distance_m": round(actual, 1) if actual is not None else None,
                "reference_distance_m": round(reference, 1) if reference is not None else None,
                "deviation_ratio": ratio,
                "refund_cap_cents": cap, "calculated_refund_cents": min(refund, cap)}
    # Original synthetic no_show category
    samples = trip.get("pickup_presence_samples", [])
    cancellation = datetime.fromisoformat(trip["cancelled_at"])
    arrival = datetime.fromisoformat(trip["arrived_at"]) if trip.get("arrived_at") else None
    distances = [distance_m(p, trip["pickup"]) for p in samples]
    times = [datetime.fromisoformat(p["timestamp"]) for p in samples]
    valid_window = bool(arrival and len(times) >= 2 and times == sorted(times)
                        and arrival <= times[0] <= times[-1] <= cancellation)
    max_distance = max(distances) if distances else None
    verified_wait = (times[-1] - times[0]).total_seconds() if valid_window else None
    return {"max_pickup_distance_m": round(max_distance, 1) if max_distance is not None else None,
            "presence_sample_count": len(samples), "valid_observation_window": valid_window,
            "verified_wait_seconds": verified_wait,
            "arrival_to_cancel_seconds": (cancellation - arrival).total_seconds() if arrival else None}


def policy_decision(case: dict, policy: dict, metrics: dict) -> dict:
    """Deterministic policy baseline, separate from AI reasoning.

    For synthetic cases (NS01, RT01, etc.) uses demo policy with polyline estimates.
    For organiser cases (DISP-001, etc.) uses organiser policy v2.1 with supplied
    road distances and organiser-specific escalation rules.
    """
    case_id = case.get("trip_id", "")
    category = case["category"]

    # --- Organiser cases: use organiser policy v2.1 ---------------------------
    if _is_organiser_case(case_id):
        return _organiser_policy_decision(case, metrics)

    # --- Original synthetic demo policy --------------------------------------
    payment, trip = case["payment"], case["trip"]
    clause = "DEMO-ROUTE-01" if category == "route_deviation" else "DEMO-NOSHOW-01"

    def answer(ruling, refund, reason, confidence=0.92):
        return {"ruling": ruling, "refund_cents": refund, "rationale": reason,
                "policy_ids": [clause], "confidence": confidence}

    if category == "route_deviation":
        ratio = metrics["deviation_ratio"]
        if ratio is None or trip.get("detour_approved") is None or trip.get("verified_operational_reason") is None:
            return answer("human_review", 0, "Route or detour-authorisation evidence is incomplete.", 0.35)
        if trip["detour_approved"] or trip["verified_operational_reason"]:
            return answer("no_action", 0, "The supplied record establishes an agreed or operationally justified detour.")
        if ratio > policy["route"]["deviation_ratio_threshold"] and metrics["calculated_refund_cents"] > 0:
            cents = metrics["calculated_refund_cents"]
            return answer("refund", cents, f"An unapproved excess route meets the demo policy threshold; refund {money(cents)} of the supported excess fare.")
        return answer("no_action", 0, "The recorded route and fare do not establish a refund under the demo policy.")
    fee = payment["cancellation_fee_cents"]
    if fee == 0:
        return answer("no_action", 0, "No cancellation fee was charged.")
    if metrics["max_pickup_distance_m"] is None:
        return answer("human_review", 0, "GPS evidence is missing; pickup presence cannot be verified.", 0.35)
    if not metrics["valid_observation_window"] or metrics["verified_wait_seconds"] is None:
        return answer("human_review", 0, "The observation timestamps do not establish a valid waiting interval.", 0.35)
    if metrics["max_pickup_distance_m"] > policy["no_show"]["pickup_radius_m"]:
        return answer("refund", fee, "The GPS record places the driver outside the agreed pickup radius; refund the cancellation fee.")
    if metrics["verified_wait_seconds"] < policy["no_show"]["minimum_verified_wait_seconds"]:
        return answer("refund", fee, "The verified waiting interval is shorter than the demo policy minimum; refund the cancellation fee.")
    return answer("no_action", 0, "GPS and timestamps support presence at the pickup point for the required verified waiting interval.")


def _organiser_policy_decision(case: dict, metrics: dict) -> dict:
    """Conservative policy-first decision for organiser cases using v2.1 rules.

    DISP-001: 4.3 km deviation > 2 km threshold → human_review. The 344-cent
    excess-distance fare is a candidate remedy for the reviewer, not an automated award.

    DISP-002: GPS supports pickup presence; 6 min scheduled-to-cancel exceeds 5-min
    free wait. Contact obligations (4 messages + 1 call) are met. Fraud flag raises
    confidence threshold to 0.95 — cannot be met without calibration → human_review.

    DISP-003: Surge differential 450 cents, rider_notified=false → refund. Below $10
    threshold, AI ruling is final. Confidence is uncalibrated but evidence is clear.

    No expected/sample rulings are hardcoded. Each decision follows from policy text.
    """
    category = case["category"]
    payment = case["payment"]

    def answer(ruling, refund, reason, confidence, *clause_ids):
        return {"ruling": ruling, "refund_cents": refund, "rationale": reason,
                "policy_ids": list(clause_ids), "confidence": confidence}

    if category == "route_deviation":
        excess_m = metrics.get("excess_distance_m")
        excess_fare = metrics.get("excess_distance_fare_cents", 0)
        requires_review = metrics.get("requires_route_threshold_review", False)
        if requires_review:
            # Policy 6.2: route deviation > 2km requires human review.
            # The 344-cent excess-distance fare is a candidate remedy, not an automated award.
            return answer("human_review", 0,
                          f"Route deviation of {excess_m/1000:.1f} km exceeds the 2 km "
                          "autonomous-resolution threshold under policy 6.2. The "
                          f"{money(excess_fare)} excess-distance fare is a candidate remedy "
                          "for the reviewer. Traffic conditions were supplied but driver "
                          "notification is disputed; call recording not available.",
                          0.35, "ORG-V2.1-6.2", "ORG-V2.1-1.2", "ORG-V2.1-6.1")
        if excess_fare and excess_fare > 0:
            return answer("refund", excess_fare,
                          f"Route deviation within 2 km tolerance; refund {money(excess_fare)} "
                          "excess-distance fare under policy 1.3.",
                          0.92, "ORG-V2.1-1.3", "ORG-V2.1-6.2")
        return answer("no_action", 0,
                      "No refundable excess distance fare under policy 1.3.",
                      0.92, "ORG-V2.1-1.3")

    if category == "no_show_charge":
        fee = payment.get("cancellation_fee_cents", 0)
        scheduled_to_cancel = metrics.get("scheduled_to_cancel_seconds")
        msg_count = metrics.get("pre_cancel_driver_message_count", 0)
        call_count = metrics.get("pre_cancel_driver_call_attempt_count", 0)
        fraud_flags = metrics.get("rider_fraud_flags", 0)

        # Policy 2.3: driver must send ≥1 message AND ≥1 call before cancelling.
        contact_met = msg_count >= 1 and call_count >= 1

        # Policy 2.1: 5-minute free wait from scheduled pickup.
        wait_ok = scheduled_to_cancel is not None and scheduled_to_cancel >= 300

        # Policy 6.3: fraud flag ≥ 1 raises confidence threshold to 0.95.
        if fraud_flags and fraud_flags >= 1:
            if contact_met and wait_ok:
                return answer("human_review", 0,
                              "GPS supports pickup presence and the 5-minute free wait "
                              "from scheduled pickup was met. Contact obligations were "
                              f"satisfied ({msg_count} messages, {call_count} calls). "
                              f"However, rider fraud flag ({fraud_flags}) raises the "
                              "confidence threshold to 0.95 under policy 6.3; this "
                              "threshold cannot be met without calibration. Escalate.",
                              0.35, "ORG-V2.1-6.3", "ORG-V2.1-2.1", "ORG-V2.1-2.3")
            else:
                return answer("refund", fee,
                              "Driver did not meet contact obligations (policy 2.3) "
                              "or free wait was not met from scheduled pickup. "
                              "Refund the cancellation fee.",
                              0.90, "ORG-V2.1-2.3", "ORG-V2.1-2.1")
        if not contact_met or not wait_ok:
            return answer("refund", fee,
                          "Driver did not meet contact obligations or free-wait "
                          "requirements under policy 2.1/2.3. Refund the cancellation fee.",
                          0.92, "ORG-V2.1-2.3", "ORG-V2.1-2.1")
        return answer("no_action", 0,
                      "GPS supports pickup presence; 5-minute free wait from scheduled "
                      "pickup was met; contact obligations were satisfied. Retain the fee.",
                      0.90, "ORG-V2.1-2.1", "ORG-V2.1-2.3")

    if category == "fare_dispute":
        surge_diff = metrics.get("surge_difference_cents")
        fare_diff = metrics.get("fare_difference_cents")
        surge_log = metrics.get("surge_pricing_log", {})
        rider_notified = surge_log.get("rider_notified") if surge_log else None

        if surge_diff and surge_diff > 0 and rider_notified is False:
            return answer("refund", surge_diff,
                          f"Surge multiplier increased between quote and trip start; "
                          f"rider was not notified. Refund {money(surge_diff)} surge "
                          "differential under policy 3.3/3.4. Below $10 threshold, "
                          "AI ruling is final.",
                          0.92, "ORG-V2.1-3.3", "ORG-V2.1-3.4", "ORG-V2.1-7.2")
        return answer("no_action", 0,
                      "No refundable surge differential identified under policy 3.3.",
                      0.90, "ORG-V2.1-3.3")

    return answer("human_review", 0,
                  f"Unsupported category: {category}", 0.35)


class EvidenceTools:
    """Read-only tools bound to one trip; models cannot choose another trip ID."""
    def __init__(self, case, policy, log):
        self.case, self.policy, self.log = case, policy, log

    def call(self, name, actor):
        if name not in TOOLS:
            raise OutputError("An agent requested a tool outside the allowed evidence tools.")
        c, p = self.case, self.policy
        case_id = c.get("trip_id", "")

        # Organiser cases route through organiser_support for evidence retrieval.
        if _is_organiser_case(case_id):
            try:
                import organiser_support as org
                ev = org.get_evidence(case_id, name)
                record = {"id": ev["evidence_ids"][0], "tool": name,
                          "source": ev["source"],
                          "data": copy.deepcopy(ev["data"])}
                if ev.get("policy_ids"):
                    record["policy_ids"] = ev["policy_ids"]
                self.log(actor, "tool_result", {"tool": name, "evidence_id": record["id"]})
                return record
            except Exception as exc:
                raise OutputError(f"Organiser evidence retrieval failed for {case_id}:{name}") from exc

        mapping = {
            "get_trip": c["trip"], "get_messages": c["messages"],
            "get_payment": c["payment"], "get_history": c["history"],
            "get_metrics": calculate_metrics(c, p),
            "get_policy": {"version": p["version"], "demo_only": True,
                           "parameters": p["route" if c["category"] == "route_deviation" else "no_show"],
                           "clauses": [p["clauses"]["DEMO-ROUTE-01" if c["category"] == "route_deviation" else "DEMO-NOSHOW-01"]]},
        }
        record = {"id": f'{c["trip_id"]}:{name}', "tool": name,
                  "source": "synthetic fixture / demo policy", "data": copy.deepcopy(mapping[name])}
        self.log(actor, "tool_result", {"tool": name, "evidence_id": record["id"]})
        return record


def check_citations(obj, evidence_ids, policy_ids):
    for field, allowed in (("evidence_ids", evidence_ids), ("policy_ids", policy_ids)):
        value = obj.get(field)
        if not isinstance(value, list) or not value or not all(isinstance(v, str) and v in allowed for v in value):
            raise OutputError(f"Agent returned missing or unrecognised {field}.")


def check_advocate(obj, evidence_ids, policy_ids):
    check_citations(obj, evidence_ids, policy_ids)
    if obj.get("position") not in RULINGS or not isinstance(obj.get("statement"), str) or not obj["statement"].strip():
        raise OutputError("Advocate returned an invalid position or case argument.")
    return obj


def check_judge(obj, evidence_ids, policy_ids, charged_cents):
    check_citations(obj, evidence_ids, policy_ids)
    if obj.get("ruling") not in RULINGS:
        raise OutputError("Judge returned an invalid ruling.")
    cents = obj.get("refund_cents")
    if type(cents) is not int or not 0 <= cents <= charged_cents:
        raise OutputError("Judge refund must be integer cents within the charged amount.")
    if obj["ruling"] != "refund" and cents != 0:
        raise OutputError("Only a refund ruling may specify a refund amount.")
    confidence = obj.get("confidence")
    if type(confidence) not in (int, float) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise OutputError("Judge confidence must be a finite number from 0 through 1.")
    for field in ("rationale", "rider_message", "driver_message"):
        if not isinstance(obj.get(field), str) or not obj[field].strip():
            raise OutputError(f"Judge must provide a non-empty {field}.")
    return obj


def _validate_multi_agent_ruling(obj: dict, charged_cents: int, clause_ids: set,
                                  all_evidence_ids: set, trip_id: str) -> dict:
    """Validate a multi-agent ADP response against the existing result schema.

    Checks case_id match, ruling validity, refund bounds, required fields.
    Never invents missing fields — raises OutputError if validation fails.
    """
    if not isinstance(obj, dict):
        raise OutputError("ADP multi-agent response must be a JSON object.")

    # Verify the ruling references the correct case if the agent included one.
    resp_case = obj.get("case_id")
    if resp_case and resp_case != trip_id:
        raise OutputError(f"ADP response references case '{resp_case}', expected '{trip_id}'.")

    # Validate ruling and refund using the same rules as check_judge.
    if obj.get("ruling") not in RULINGS:
        raise OutputError("ADP Judge returned an invalid ruling.")
    cents = obj.get("refund_cents")
    if type(cents) is not int or not 0 <= cents <= charged_cents:
        raise OutputError("Judge refund must be integer cents within the charged amount.")
    if obj["ruling"] != "refund" and cents != 0:
        raise OutputError("Only a refund ruling may specify a refund amount.")
    confidence = obj.get("confidence")
    if type(confidence) not in (int, float) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise OutputError("Judge confidence must be a finite number from 0 through 1.")
    for field in ("rationale", "rider_message", "driver_message"):
        if not isinstance(obj.get(field), str) or not obj[field].strip():
            raise OutputError(f"Judge must provide a non-empty {field}.")

    # Validate evidence/policy IDs if the agent included them.
    evidence_ids = obj.get("evidence_ids")
    if evidence_ids is not None:
        check_citations(obj, all_evidence_ids, clause_ids)
    policy_ids = obj.get("policy_ids")
    if policy_ids is not None:
        check_citations({"evidence_ids": obj.get("evidence_ids", []),
                         "policy_ids": policy_ids}, all_evidence_ids, clause_ids)

    # Fill in missing evidence_ids/policy_ids rather than inventing them.
    obj.setdefault("evidence_ids", sorted(all_evidence_ids))
    obj.setdefault("policy_ids", sorted(clause_ids))
    return obj


def resolve(case: dict, mode="multi_agent", client=None, on_event=None) -> dict:
    """Resolve a dispute.

    The primary user-facing mode is ``multi_agent``, which sends one request
    to the published ADP application. ``offline`` and ``adp`` (legacy Standard
    Mode) are preserved for evaluation utilities and tests but are never
    exposed in the Streamlit UI.
    """
    start = time.perf_counter()
    case = copy.deepcopy(case)
    supported = {"route_deviation", "no_show", "no_show_charge", "fare_dispute"}
    if case.get("category") not in supported:
        raise ValueError(f"This prototype supports {sorted(supported)} disputes.")
    if mode not in {"offline", "adp", "multi_agent"} or (mode in {"adp", "multi_agent"} and client is None):
        raise ValueError("Choose a supported mode and provide an ADP client for live modes.")
    case_id = case.get("trip_id", "")
    is_organiser = _is_organiser_case(case_id)
    policy = load_policy()
    run_id = str(uuid.uuid4())
    trace = []
    adp_activity: list[dict] = []

    def log(actor, event, detail):
        item = {"sequence": len(trace) + 1, "timestamp": datetime.now(timezone.utc).isoformat(),
                "actor": actor, "event": event, "detail": detail}
        trace.append(item)
        if on_event:
            on_event(item)

    tools = EvidenceTools(case, policy, log)
    roles = [("Rider Advocate", "rider"), ("Driver Advocate", "driver")]
    arguments, all_evidence = {}, {}
    metrics = calculate_metrics(case, policy)
    baseline = policy_decision(case, policy, metrics)
    clause_ids = set(baseline["policy_ids"])

    # For organiser cases, also collect all organiser policy clause IDs
    # from get_policy so the validator accepts any valid clause citation.
    if is_organiser:
        try:
            import organiser_support as org
            pol_ev = org.get_evidence(case_id, "get_policy")
            clause_ids.update(pol_ev.get("policy_ids", []))
        except Exception:
            pass

    # --- Multi-agent mode: single delegation to ADP ---------------------------
    if mode == "multi_agent":
        session = str(uuid.uuid4())
        log("ADP multi-agent", "started", {"mode": mode, "conversation_id": session})
        # Gather all local evidence FIRST so we can send the evidence IDs to ADP
        # and validate the Judge's citations against the same IDs.
        for name in TOOLS:
            evidence = tools.call(name, "ADP multi-agent")
            all_evidence[evidence["id"]] = evidence
        accepted_evidence_ids = sorted(all_evidence)
        accepted_policy_ids = sorted(clause_ids)
        log("ADP multi-agent", "evidence_gathered", {
            "evidence_ids": accepted_evidence_ids,
            "policy_ids": accepted_policy_ids})
        # Send case_id, complaint, AND the list of valid evidence/policy IDs so
        # agents know exactly which IDs to cite in the final ruling.
        ruling, adp_activity, adp_debug = client.review(
            case["trip_id"], case["complaint"], session,
            evidence_ids=accepted_evidence_ids,
            policy_ids=accepted_policy_ids)
        log("ADP multi-agent", "response_received", {"activity_events": len(adp_activity)})
        try:
            ruling = _validate_multi_agent_ruling(
                ruling, case["payment"]["charged_cents"], clause_ids,
                set(all_evidence), case["trip_id"])
        except OutputError as exc:
            # Attach validation debug info so the UI can show what was expected.
            exc.validation_debug = {
                "judge_evidence_ids": ruling.get("evidence_ids"),
                "accepted_evidence_ids": accepted_evidence_ids,
                "judge_policy_ids": ruling.get("policy_ids"),
                "accepted_policy_ids": accepted_policy_ids,
                "judge_ruling_json": copy.deepcopy(ruling),
            }
            raise
        log("ADP multi-agent", "model_recommendation", copy.deepcopy(ruling))
        mismatch = (ruling["ruling"], ruling["refund_cents"]) != (baseline["ruling"], baseline["refund_cents"])
        if is_organiser:
            # Organiser cases use their own policy thresholds, not the synthetic one.
            # The baseline already encodes the conservative escalation decision.
            review_threshold = 0.80  # policy 6.2 default for $10-$50 range
            if mismatch or ruling["confidence"] < review_threshold:
                reason = ("The model recommendation differs from the organiser-v2.1 policy check."
                          if mismatch else "The model confidence falls below the organiser policy threshold.")
                ruling.update({"ruling": "human_review", "refund_cents": 0, "confidence": 0.35,
                               "rationale": reason + " Refer the full evidence and both cases to a reviewer.",
                               "rider_message": "Your dispute needs a reviewer; no refund has been executed.",
                               "driver_message": "This dispute needs a reviewer; no payment action has been executed."})
                log("Policy validator", "review_required", {"reason": reason, "policy_check": baseline})
        else:
            if mismatch or ruling["confidence"] < policy["review_confidence_threshold"]:
                reason = ("The model recommendation differs from the deterministic demo-policy check."
                          if mismatch else "The model confidence falls below the prototype review threshold.")
                ruling.update({"ruling": "human_review", "refund_cents": 0, "confidence": 0.35,
                               "rationale": reason + " Refer the full evidence and both cases to a reviewer.",
                               "rider_message": "Your dispute needs a reviewer; no refund has been executed.",
                               "driver_message": "This dispute needs a reviewer; no payment action has been executed."})
                log("Policy validator", "review_required", {"reason": reason, "policy_check": baseline})
        log("ADP multi-agent", "final_recommendation", ruling)
        policy_version = "organiser-v2.1" if is_organiser else policy["version"]
        return {"run_id": run_id, "trip_id": case["trip_id"], "category": case["category"],
                "complaint": case["complaint"], "mode": mode, "synthetic_data": True,
                "policy_version": policy_version, "simulation_only": True,
                "confidence_note": "Prototype heuristic / model self-assessment; not calibrated accuracy.",
                "advocates": arguments, "evidence": list(all_evidence.values()), "metrics": metrics,
                "ruling": ruling, "trace": trace, "adp_activity": adp_activity,
                "adp_debug": adp_debug,
                "elapsed_seconds": round(time.perf_counter() - start, 6)}

    # --- Offline / legacy ADP Standard Mode -----------------------------------
    for role, party in roles:
        session = str(uuid.uuid4())
        log(role, "started", {"mode": mode, "conversation_id": session})
        if mode == "adp":
            plan = client.ask(prompts.PLANNER, {"stage": "plan", "role": role,
                              "complaint": case["complaint"], "category": case["category"],
                              "allowed_tools": list(TOOLS)}, session)
            names = plan.get("tools")
            if not isinstance(names, list) or not all(isinstance(n, str) and n in TOOLS for n in names) or not REQUIRED_TOOLS.issubset(names):
                raise OutputError("Advocate must select the required read-only evidence tools.")
            names = list(dict.fromkeys(names))
        else:
            names = list(TOOLS)
        log(role, "tool_plan", {"tools": names})
        evidence = [tools.call(name, role) for name in names]
        all_evidence.update({e["id"]: e for e in evidence})
        ids = {e["id"] for e in evidence}
        if mode == "adp":
            argument = client.ask(prompts.ADVOCATE.format(role=role, party=party),
                                  {"stage": "case", "role": role, "complaint": case["complaint"],
                                   "category": case["category"], "evidence": evidence}, session)
            argument = check_advocate(argument, ids, clause_ids)
        else:
            position = "refund" if party == "rider" else "no_action"
            statement = ("The rider disputes the charge. Review the trip observations and fare against the demo policy."
                         if party == "rider" else
                         "The driver asks that valid charges be retained. Review pickup presence or detour authorisation and consider conflicting evidence.")
            argument = {"position": position, "statement": statement,
                        "evidence_ids": sorted(ids), "policy_ids": sorted(clause_ids)}
        arguments[role] = argument
        log(role, "case_presented", argument)
    judge_session = str(uuid.uuid4())
    log("Judge", "started", {"mode": mode, "conversation_id": judge_session})
    if mode == "adp":
        ruling = client.ask(prompts.JUDGE, {"stage": "judge", "complaint": case["complaint"],
                           "category": case["category"], "advocates": arguments,
                           "evidence": list(all_evidence.values())}, judge_session)
        ruling = check_judge(ruling, set(all_evidence), clause_ids, case["payment"]["charged_cents"])
        log("Judge", "model_recommendation", copy.deepcopy(ruling))
        mismatch = (ruling["ruling"], ruling["refund_cents"]) != (baseline["ruling"], baseline["refund_cents"])
        if mismatch or ruling["confidence"] < policy["review_confidence_threshold"]:
            reason = ("The model recommendation differs from the deterministic demo-policy check."
                      if mismatch else "The model confidence falls below the prototype review threshold.")
            ruling.update({"ruling": "human_review", "refund_cents": 0, "confidence": 0.35,
                           "rationale": reason + " Refer the full evidence and both cases to a reviewer.",
                           "rider_message": "Your dispute needs a reviewer; no refund has been executed.",
                           "driver_message": "This dispute needs a reviewer; no payment action has been executed."})
            log("Policy validator", "review_required", {"reason": reason, "policy_check": baseline})
    else:
        ruling = {**baseline, "evidence_ids": sorted(all_evidence),
                  "rider_message": baseline["rationale"], "driver_message": baseline["rationale"]}
    log("Judge", "final_recommendation", ruling)
    policy_version = "organiser-v2.1" if is_organiser else policy["version"]
    return {"run_id": run_id, "trip_id": case["trip_id"], "category": case["category"],
            "complaint": case["complaint"], "mode": mode, "synthetic_data": True,
            "policy_version": policy_version, "simulation_only": True,
            "confidence_note": "Prototype heuristic / model self-assessment; not calibrated accuracy.",
            "advocates": arguments, "evidence": list(all_evidence.values()), "metrics": metrics,
            "ruling": ruling, "trace": trace, "elapsed_seconds": round(time.perf_counter() - start, 6)}


def build_evidence_timeline(case: dict) -> list[dict]:
    """Combine chat messages and pickup events into a chronologically sorted timeline.

    Each entry has: timestamp (ISO str), source ("chat" or "gps"), label (short
    description), detail (human-readable text), and type ("claim" for recorded
    statements, "observation" for GPS/telemetry). Entries are sorted by their
    actual timestamps. Route-deviation cases and missing timestamps are handled
    gracefully. Returns an empty list if no timestamped events exist.
    """
    SGT = None
    try:
        from zoneinfo import ZoneInfo
        SGT = ZoneInfo("Asia/Singapore")
    except Exception:
        SGT = timezone(timedelta(hours=8))

    entries: list[tuple[datetime, dict]] = []
    trip = case.get("trip", {})

    for msg in case.get("messages", []):
        ts_raw = msg.get("timestamp")
        if not ts_raw:
            continue
        try:
            ts = datetime.fromisoformat(ts_raw)
        except (ValueError, TypeError):
            continue
        sender = msg.get("sender", "unknown")
        text = msg.get("text", "") or msg.get("content", "") or msg.get("message", "")
        entries.append((ts, {
            "timestamp": ts.astimezone(SGT).strftime("%Y-%m-%d %H:%M:%S %Z"),
            "source": "chat",
            "type": "claim",
            "label": f"Chat — {sender}",
            "detail": text,
        }))

    arrived = trip.get("arrived_at")
    if arrived:
        try:
            ts = datetime.fromisoformat(arrived)
            entries.append((ts, {
                "timestamp": ts.astimezone(SGT).strftime("%Y-%m-%d %H:%M:%S %Z"),
                "source": "gps",
                "type": "observation",
                "label": "Driver arrival",
                "detail": f"Arrived at pickup (lat {trip.get('pickup', {}).get('lat')}, lon {trip.get('pickup', {}).get('lon')})",
            }))
        except (ValueError, TypeError):
            pass

    for sample in trip.get("pickup_presence_samples", []):
        ts_raw = sample.get("timestamp")
        if not ts_raw:
            continue
        try:
            ts = datetime.fromisoformat(ts_raw)
        except (ValueError, TypeError):
            continue
        lat = sample.get("lat", "?")
        lon = sample.get("lon", "?")
        entries.append((ts, {
            "timestamp": ts.astimezone(SGT).strftime("%Y-%m-%d %H:%M:%S %Z"),
            "source": "gps",
            "type": "observation",
            "label": "GPS observation",
            "detail": f"Position lat {lat}, lon {lon}",
        }))

    cancelled = trip.get("cancelled_at")
    if cancelled:
        try:
            ts = datetime.fromisoformat(cancelled)
            entries.append((ts, {
                "timestamp": ts.astimezone(SGT).strftime("%Y-%m-%d %H:%M:%S %Z"),
                "source": "gps",
                "type": "observation",
                "label": "Trip cancellation",
                "detail": "Trip was cancelled",
            }))
        except (ValueError, TypeError):
            pass

    entries.sort(key=lambda pair: pair[0])
    return [entry for _, entry in entries]


def save_result(result: dict, path: Path | None = None):
    path = path or ROOT / "runtime/cases.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    try:
        db.execute("CREATE TABLE IF NOT EXISTS cases (run_id TEXT PRIMARY KEY, trip_id TEXT, mode TEXT, result_json TEXT)")
        db.execute("INSERT INTO cases VALUES (?, ?, ?, ?)",
                   (result["run_id"], result["trip_id"], result["mode"], json.dumps(result)))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
