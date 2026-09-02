#!/usr/bin/env python3
"""Register every chronicle column and stream, so a panel with no data reads empty, not red.

    python openobserve/seed_schema.py
    python openobserve/seed_schema.py --dry-run                              # print what it would send
    python openobserve/seed_schema.py openobserve/chronicle.dashboard.json   # ...and check it, too

Run this once against a fresh OpenObserve, and again after adding a chronicle column. It is
idempotent -- seeding a column that already exists changes nothing.

WHY THIS EXISTS
---------------
OpenObserve registers a column the first time some record carries it. A query naming a column that
has never arrived does not return zero rows: it fails at planning with `unknown field`, and the
panel renders a red error. Same for a stream that does not exist yet. So on a machine where
`chronicle_export.py` has not run, every panel on the chronicle dashboard is red rather than empty --
which reads as "the dashboard is broken" rather than "no history has been loaded yet".

Sending one record per stream carrying every column the panels name fixes that at the source: the
query plans, matches nothing real, and the panel says "No Data Found".

WHY THE COLUMN LIST IS NOT WRITTEN HERE
---------------------------------------
It is read out of `chronicle_export.JOBS` -- the same table that decides what the exporter sends --
so the two cannot drift. A list maintained here would be the one that goes stale, and a stale entry
is exactly a red panel. `derived` and `expressions` are included for the same reason: `ai_credits`,
the seven credit columns and the two prompt lengths exist only in the row the exporter builds, and
they are as real to a panel as a copied column.

WHAT IT COSTS, AND THE ONE RULE A NEW PANEL MUST FOLLOW
-------------------------------------------------------
One seed row per stream, whose `service_user` is the literal `schema_seed`. **Every chronicle panel
must exclude that value by name** -- `AND <alias>.service_user <> 'schema_seed'` -- on both sides of
any join.

The Developer dropdown cannot offer `schema_seed` as a choice, which looks like enough. It is not:
the variable has `selectAllValueForMultiSelect: "all"`, and All does not mean "every value in the
list", it stops restricting the column at all. Relying on the dropdown put a phantom row on seven
chronicle panels -- 311 sessions for 310, plus a `schema_seed` model, project and initiator. A
chronicle panel *counts rows*, so a seed row that gets through does not add a harmless zero; it adds
one to a headline count and a phantom entry to every GROUP BY.

Nothing detects the omission for you. The panel simply reads one too many.

TYPES
-----
The seeded value fixes the column's type, and OpenObserve widens a column to Utf8 if a later record
disagrees -- nothing is dropped, but an uncast `SUM` over a widened column then fails. So numeric
columns are seeded as 0 and everything else as the marker string.

Chronicle has no string-typed counters, which is why there is no exception table here: every number
comes out of SQLite as a number. That is worth knowing if this is ever pointed at another producer --
Claude Code sends `duration_ms` as a *string*, and one shared exception list that widened
`copilot_chronicle_usage.duration_ms` to Utf8 took the model-latency panel down with it. Nothing
failed at seed time; the panel went red on the next validate.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# The repository root too, because chronicle_export.py is loaded from there below and imports
# openobserve_export from beside itself. Without this, running this script from any directory but
# the root fails on that import rather than on anything to do with schemas.
sys.path.insert(1, str(Path(__file__).resolve().parent.parent))

import oo_api  # noqa: E402

SEED_MARKER = "schema_seed"
NUMERIC_COLUMN = re.compile(
    r"tokens|cost|aiu|duration|count|lines|temperature|bytes|_ms\b"
    r"|credits|multiplier|_index|_row_id|triggered|exit_code")
STREAM_REFERENCE = re.compile(r"\b(?:FROM|JOIN)\s+([a-z0-9_]+)", re.IGNORECASE)


def chronicle_columns() -> dict:
    """Stream -> columns, read from chronicle_export.py itself. See WHY THE COLUMN LIST IS NOT HERE.

    Loaded with importlib rather than imported, because this file lives one directory down and the
    exporter is not a package. Only constants and definitions run: `main()` is guarded by
    `__main__`.
    """
    source = Path(__file__).resolve().parent.parent / "chronicle_export.py"
    if not source.exists():
        raise SystemExit("cannot find chronicle_export.py next to the repository root")
    spec = importlib.util.spec_from_file_location("chronicle_export", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    plan = {}
    for job in module.JOBS:
        plan[job["stream"]] = (set(job["columns"])
                               | set(job.get("derived", ()))
                               | set(job.get("expressions", ()))
                               | {"chronicle_row_id", "service_user"})
    # chronicle_advice.py writes a stream of its own, and its first run may be days after the
    # dashboard is pushed -- or never, since it costs credits -- so its panel needs the columns
    # registered up front like any other.
    plan[module.ADVICE_STREAM] = set(module.ADVICE_COLUMNS)
    return plan


def streams_named_by(dashboard_path: str) -> set:
    """Chronicle streams some panel actually reads. Used only to check the plan, never to build it.

    A stream a panel names but nothing declares is a typo or a panel from a newer dashboard, and it
    is worth saying so: seeding cannot help it and the panel will be red.
    """
    _, dashboard = oo_api.load_dashboard(dashboard_path)
    found = set()
    for _, panel in oo_api.panels(dashboard):
        for query in panel.get("queries") or []:
            for match in STREAM_REFERENCE.finditer(query.get("query") or ""):
                name = match.group(1)
                if name.startswith("copilot_chronicle_"):
                    found.add(name)
    return found


def seed_value(column: str):
    return 0 if NUMERIC_COLUMN.search(column) else SEED_MARKER


def seed_logs(stream: str, columns: set, dry_run: bool) -> bool:
    """One record posted straight to the ingest API, the same way the real rows arrive.

    The chronicle streams bypass any collector -- chronicle has no OTel export -- so there is no
    OTLP route to seed them through.
    """
    row = {column: seed_value(column) for column in sorted(columns)}
    if "service_user" not in columns:
        print("    WARNING: %s has no service_user column, so its seed row cannot be excluded by any"
              " panel" % stream, file=sys.stderr)
    else:
        row["service_user"] = SEED_MARKER
    row["_timestamp"] = int(time.time() * 1_000_000)
    print("  logs: %d columns" % len(row))
    if dry_run:
        return True
    url = "%s/api/%s/%s/_json" % (oo_api.base_url(), oo_api.org(), stream)
    request = urllib.request.Request(
      url,
      data=json.dumps([row]).encode("utf-8"),
      headers={"Content-Type": "application/json", "Authorization": oo_api.auth_header()},
    )
    try:
        with urllib.request.urlopen(request, timeout=30, context=oo_api.ssl_context()) as response:
            return 200 <= response.status < 300
    except Exception as err:  # noqa: BLE001
        print("    failed: %r" % (err,), file=sys.stderr)
        return False


def existing() -> dict:
    ok, listing = oo_api.api("GET", "/streams")
    if not ok or not isinstance(listing, dict):
        return {}
    return {stream["name"]: stream for stream in listing.get("list", [])}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dashboard", nargs="?",
                        help="optional dashboard JSON, checked against the plan so a panel naming a "
                             "stream nothing writes is reported instead of just rendering red")
    parser.add_argument("--dry-run", action="store_true", help="print what would be sent")
    args = parser.parse_args(argv)

    plan = chronicle_columns()
    present = {} if args.dry_run else existing()

    print("seeding %d chronicle stream(s)\n" % len(plan))
    failures = 0
    for stream, columns in sorted(plan.items()):
        mark = "" if args.dry_run else ("exists" if stream in present else "MISSING")
        print("%-32s %s" % (stream, mark))
        if not seed_logs(stream, columns, args.dry_run):
            failures += 1

    if args.dashboard:
        unknown = streams_named_by(args.dashboard) - set(plan)
        if unknown:
            print("\nWARNING: %s reads %s, which nothing in chronicle_export.py writes. Those panels"
                  " will be red." % (args.dashboard, ", ".join(sorted(unknown))), file=sys.stderr)
            failures += 1

    if args.dry_run:
        print("\ndry run: nothing was sent.")
        return 0
    print("\nsent. OpenObserve registers a column within a few seconds; run")
    print("openobserve/validate_dashboard_queries.py to confirm every panel now plans.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
