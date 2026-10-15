from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import json
import math
from pathlib import Path
import sqlite3
import time
import uuid

from . import prompts

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ("get_trip", "get_messages", "get_payment", "get_metrics", "get_policy", "get_history")
REQUIRED_TOOLS = set(TOOLS) - {"get_history"}
RULINGS = {"refund", "no_action", "human_review"}


class OutputError(ValueError):
    pass


def load_cases() -> list[dict]:
    return json.loads((ROOT / "data/cases.json").read_text(encoding="utf-8"))


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
    """Deterministic demo policy check, separate from AI reasoning.

    Route lengths are polyline estimates; the reference route is supplied synthetic
    data, not a live road-network optimisation. Pickup sampling is also simulated.
    """
    payment, trip = case["payment"], case["trip"]
    clause = "DEMO-ROUTE-01" if case["category"] == "route_deviation" else "DEMO-NOSHOW-01"

    def answer(ruling, refund, reason, confidence=0.92):
        return {"ruling": ruling, "refund_cents": refund, "rationale": reason,
                "policy_ids": [clause], "confidence": confidence}

    if case["category"] == "route_deviation":
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


class EvidenceTools:
    """Read-only tools bound to one trip; models cannot choose another trip ID."""
    def __init__(self, case, policy, log):
        self.case, self.policy, self.log = case, policy, log

    def call(self, name, actor):
        if name not in TOOLS:
            raise OutputError("An agent requested a tool outside the allowed evidence tools.")
        c, p = self.case, self.policy
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
    if case.get("category") not in {"route_deviation", "no_show"}:
        raise ValueError("This prototype supports route deviation and no-show disputes.")
    if mode not in {"offline", "adp", "multi_agent"} or (mode in {"adp", "multi_agent"} and client is None):
        raise ValueError("Choose a supported mode and provide an ADP client for live modes.")
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
        if mismatch or ruling["confidence"] < policy["review_confidence_threshold"]:
            reason = ("The model recommendation differs from the deterministic demo-policy check."
                      if mismatch else "The model confidence falls below the prototype review threshold.")
            ruling.update({"ruling": "human_review", "refund_cents": 0, "confidence": 0.35,
                           "rationale": reason + " Refer the full evidence and both cases to a reviewer.",
                           "rider_message": "Your dispute needs a reviewer; no refund has been executed.",
                           "driver_message": "This dispute needs a reviewer; no payment action has been executed."})
            log("Policy validator", "review_required", {"reason": reason, "policy_check": baseline})
        log("ADP multi-agent", "final_recommendation", ruling)
        return {"run_id": run_id, "trip_id": case["trip_id"], "category": case["category"],
                "complaint": case["complaint"], "mode": mode, "synthetic_data": True,
                "policy_version": policy["version"], "simulation_only": True,
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
    return {"run_id": run_id, "trip_id": case["trip_id"], "category": case["category"],
            "complaint": case["complaint"], "mode": mode, "synthetic_data": True,
            "policy_version": policy["version"], "simulation_only": True,
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
        text = msg.get("text", "")
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
