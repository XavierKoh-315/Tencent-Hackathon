"""Verify the eight displayed cases. Default is local and uses no ADP tokens.

Explicit live usage: python verify_cases.py --live --cases NS02
Credentials stay in your local .env or environment. No key is printed or saved.
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from disputes.adp import ADPClient, ADPError, settings
from disputes.core import load_cases, resolve, OutputError
from human_review_store import model_confidence_for

ROOT = Path(__file__).resolve().parent
EXPECTED = {"NS01": ("refund", 500), "NS02": ("no_action", 0),
            "NS03": ("refund", 500), "NS04": ("human_review", 0),
            "RT01": ("refund", 369), "RT02": ("no_action", 0),
            "DISP-001": ("human_review", 0), "DISP-003": ("refund", 450)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Explicitly use ADP tokens; no automatic retries")
    parser.add_argument("--cases", nargs="+", choices=list(EXPECTED), help="Case IDs to test, in order")
    args = parser.parse_args()
    if args.live and not args.cases:
        parser.error("Live mode requires --cases so you explicitly select token-consuming calls.")
    ids = args.cases or list(EXPECTED)
    cases = {c["trip_id"]: c for c in load_cases()}
    client = None
    if args.live:
        try:
            client = ADPClient(settings(ROOT))
        except ADPError:
            parser.error("ADP is not configured. Set ADP_APP_KEY privately in .env or your environment.")
    report = {"mode": "live_adp" if args.live else "local_policy_only", "created_at":datetime.now(timezone.utc).isoformat(),
              "note":"Local baseline checks do not establish published agent behaviour. Live tests use real tokens. Expected outcomes are never passed to ADP.", "cases":[]}
    failures = 0
    print("LIVE ADP TEST — consumes tokens" if args.live else "LOCAL POLICY CHECK — no ADP calls or tokens")
    for cid in ids:
        try:
            result = resolve(cases[cid], mode="multi_agent" if args.live else "offline", client=client)
            ruling = result["ruling"]
            actual = (ruling["ruling"], ruling["refund_cents"])
            passed = actual == EXPECTED[cid]
            failures += not passed
            entry = {"case_id":cid, "category":cases[cid]["category"], "title":cases[cid]["title"],
                     "expected_ruling":EXPECTED[cid][0], "expected_refund_cents":EXPECTED[cid][1],
                     "validated_ruling":actual[0], "validated_refund_cents":actual[1],
                     "matches_expected":passed, "confidence":model_confidence_for(result),
                     "confidence_note":"Uncalibrated model estimate in live mode; policy heuristic in local mode",
                     "elapsed_seconds":result["elapsed_seconds"], "rationale":ruling["rationale"],
                     "evidence_ids":ruling["evidence_ids"], "policy_ids":ruling["policy_ids"]}
            if args.live:
                entry["original_model_output"] = result.get("original_ai_ruling")
                entry["activity_events_received"] = len(result.get("adp_activity", []))
            report["cases"].append(entry)
            print(f'{cid:8} {"PASS" if passed else "DIFF"}  {actual[0]:12}  refund={actual[1]} cents')
        except (ADPError, OutputError, ValueError, OSError):
            failures += 1
            # Raw remote errors may echo request details; keep this report credential-free.
            report["cases"].append({"case_id":cid, "error":"Request or validation failed; no accepted decision."})
            print(f"{cid:8} ERROR: no accepted decision. Check application configuration and quota privately.")
            if args.live:
                print("Stopping after the first failure to avoid wasting tokens.")
                break
    out = ROOT / "runtime"
    out.mkdir(exist_ok=True)
    path = out / ("live_verification.json" if args.live else "local_verification.json")
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    print(f"Report saved to {path}")
    return int(failures > 0)


if __name__ == "__main__":
    raise SystemExit(main())
