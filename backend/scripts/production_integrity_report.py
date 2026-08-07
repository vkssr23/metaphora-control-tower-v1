"""Read-only Phase 2A operator entrypoint. It never opens a database connection."""
import argparse
import json
import os
from pathlib import Path

from app.infrastructure.index_manifest import compare_indexes
from app.production_integrity import evaluate_environment, evaluate_production_readiness, scan_integrity

def main(argv=None):
    parser=argparse.ArgumentParser(description="Generate a bounded read-only integrity report from an approved JSON export")
    parser.add_argument("--input",type=Path,help="JSON object mapping collection names to bounded record arrays")
    parser.add_argument("--environment",required=True)
    parser.add_argument("--observed-indexes",type=Path)
    parser.add_argument("--json",action="store_true")
    parser.add_argument("--max-findings",type=int,default=500,choices=range(1,1001),metavar="1..1000")
    args=parser.parse_args(argv)
    records=json.loads(args.input.read_text(encoding="utf-8")) if args.input else {}
    integrity=scan_integrity(records,environment=args.environment,max_findings=args.max_findings)
    observed=json.loads(args.observed_indexes.read_text(encoding="utf-8")) if args.observed_indexes else None
    indexes=compare_indexes(observed) if observed is not None else None
    env=evaluate_environment({**os.environ,"APP_ENV":args.environment})
    readiness=evaluate_production_readiness(env,integrity,indexes)
    output={"readiness":readiness,"integrity":integrity,"environment":env,"indexes":indexes,"read_only":True}
    if args.json: print(json.dumps(output,sort_keys=True))
    else: print(f"{readiness['status']}: {integrity['summary']['total_findings']} findings; indexes {readiness['index_verification']}; no data changed")
    return 2 if readiness["status"]=="FAIL" else 0

if __name__=="__main__": raise SystemExit(main())
