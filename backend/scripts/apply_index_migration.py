"""Designed interface for a future idempotent index-migration apply tool.

--plan is fully implemented and read-only: it prints the staged manifest
plan (via index_migration_preflight.staged_migration_order) and exits 0.

--apply is intentionally NOT implemented in this change. It parses its
flags, validates them, and then refuses to proceed — no Mongo client is
ever constructed on this path. Building the real create-only apply logic
is a separate, explicitly authorized change.

Planned contract for that future change (not built here):
  * --apply requires --yes-i-am-sure-this-is-production plus typing the
    literal confirmation phrase APPLY_INDEX_MIGRATION on stdin.
  * Runs index_migration_preflight first; refuses to apply if any unique
    index reports unique_conflicts > 0 (duplicates must be resolved first,
    manually, outside this tool).
  * create_index(..., background=True) only, one index at a time, in the
    staged order (critical unique/security, then TTL, then performance).
    Never drop_index/drop/repair — an index that already exists with the
    same definition is a no-op (idempotent); a name collision with a
    different definition is a hard error, not an auto-repair.
  * Every action is logged with collection/index name only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.index_migration_preflight import staged_migration_order


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--yes-i-am-sure-this-is-production", action="store_true", dest="confirmed")
    args = parser.parse_args(argv)

    if args.plan:
        print(json.dumps({"status": "PLAN", "staged_migration_order": staged_migration_order()}, sort_keys=True))
        return 0

    # --apply: deliberately unimplemented. No client_factory, no MONGO_URL
    # read, no import of motor here — this path cannot touch a database.
    print(json.dumps({
        "status": "NOT_IMPLEMENTED",
        "reason": "apply mode is designed but intentionally not implemented pending separate authorization",
    }, sort_keys=True))
    return 3


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
