"""Evaluate the declared synthetic scenarios. Labels never go into agent inputs.

This utility is separate from the Streamlit app. It supports:
  --mode offline      — deterministic demo baseline (no AI calls)
  --mode adp          — legacy single-agent ADP Standard Mode
The app itself only exposes multi_agent mode to users.
"""
import argparse
import json
from pathlib import Path
import statistics

from disputes.adp import ADPClient, settings
from disputes.core import load_cases, resolve

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["offline", "adp"], default="offline",
                        help="offline = deterministic baseline; adp = legacy single-agent mode")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    expected = json.loads((root / "data/expected_results.json").read_text())
    client = ADPClient(settings(root)) if args.mode == "adp" else None
    rows = []
    print(f"Synthetic scenarios / demo-v1 policy / mode: {args.mode}")
    for case in load_cases():
        result = resolve(case, mode=args.mode, client=client)
        verdict = result["ruling"]
        match = all(verdict[k] == value for k, value in expected[case["trip_id"]].items())
        row = {"trip_id": case["trip_id"], "match": match, "ruling": verdict["ruling"],
               "refund_cents": verdict["refund_cents"], "seconds": result["elapsed_seconds"]}
        rows.append(row)
        print(json.dumps(row))
    print(f'Policy outcome agreement: {sum(r["match"] for r in rows)}/{len(rows)}')
    print(f'Median measured latency: {statistics.median(r["seconds"] for r in rows):.3f}s')
    if args.mode == "offline":
        print("This verifies the deterministic demo baseline; it is not an AI accuracy result.")
    raise SystemExit(0 if all(r["match"] for r in rows) else 1)

if __name__ == "__main__":
    main()
