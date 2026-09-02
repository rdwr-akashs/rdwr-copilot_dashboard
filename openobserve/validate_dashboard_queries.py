#!/usr/bin/env python3
"""Run every panel query of a dashboard export against a live OpenObserve.

    python openobserve/validate_dashboard_queries.py openobserve/chronicle.dashboard.json
    python openobserve/validate_dashboard_queries.py <dashboard.json> --days 7
    python openobserve/validate_dashboard_queries.py <dashboard.json> --var developer=AkashS

Credentials come from $OPENOBSERVE_USER / $OPENOBSERVE_PASSWORD, the same pair the exporter uses.
A panel variable such as ${developer} is replaced with a quoted literal: a probe that matches
nothing by default, so a run without --var proves the SQL parses but reports rows=0 everywhere.
Pass --var to check the numbers as well.

Exit code is the number of failing queries, so this is usable as a gate. A FAIL is almost always a
column OpenObserve has never seen -- run openobserve/seed_schema.py and try again.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import oo_api  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dashboard")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--var", action="append", default=[], metavar="NAME=VALUE",
                        help="value for a dashboard variable, e.g. --var developer=AkashS. "
                             "Repeatable. Without it a variable becomes a literal that matches "
                             "nothing, which checks the SQL parses but reports rows=0.")
    args = parser.parse_args(argv)

    # A dashboard variable is substituted as a quoted SQL literal, because every panel here uses one
    # the way OpenObserve's multi-select variables are meant to be used -- `IN (${developer})`, never
    # `= '${developer}'`. Quoting here and not in the panel is what makes both forms impossible to
    # mix up: a panel that quoted it itself would produce `= ''AkashS''` and fail to parse.
    overrides = {}
    for pair in args.var:
        name, _, value = pair.partition("=")
        overrides[name.strip()] = value

    end_us = int(time.time() * 1_000_000)
    start_us = end_us - args.days * 24 * 3600 * 1_000_000

    _, dashboard = oo_api.load_dashboard(args.dashboard)
    failures = 0
    for tab in dashboard.get("tabs") or []:
        panels = sorted(tab.get("panels") or [],
                        key=lambda panel: (panel["layout"]["y"], panel["layout"]["x"]))
        for panel in panels:
            for query in panel.get("queries") or []:
                sql = re.sub(r"\$\{([^}]+)\}",
                             lambda match: "'%s'" % overrides.get(match.group(1).strip(),
                                                                  "PROBE_VALUE"),
                             query["query"])
                ok, result = oo_api.search(
                  sql, start_us, end_us,
                  stream_type=(query.get("fields") or {}).get("stream_type", "logs"),
                )
                if not ok:
                    failures += 1
                    print("FAIL  %-58s %s" % (panel["title"][:58], result))
                    continue
                hits = result.get("hits") or []
                sample = str(hits[0])[:100] if hits else ""
                print("PASS  %-58s rows=%-3s %s" % (panel["title"][:58], len(hits), sample))

    print("\nfailures: %d" % failures)
    return failures


if __name__ == "__main__":
    sys.exit(main())
