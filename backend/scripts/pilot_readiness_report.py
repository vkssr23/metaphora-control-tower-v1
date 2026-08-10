"""Bounded operator report; never prints configuration or secret values."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pilot_readiness import evaluate_pilot_readiness


def main(argv=None):
    parser = argparse.ArgumentParser(description="Evaluate controlled-staging pilot readiness")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = evaluate_pilot_readiness(os.environ)
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print("METAPHORA PILOT READINESS")
        for gate in report["gates"]:
            print(f"{gate['gate']}: {gate['status'].upper()} ({gate['code']})")
        print(f"Overall: {report['verdict']}")
        for gate in report["gates"]:
            if gate["status"] in {"blocked", "unknown"}:
                print(f"Next: {gate['next_step']}")
    return 0 if report["status"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
