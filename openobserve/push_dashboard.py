#!/usr/bin/env python3
"""Push a dashboard file to OpenObserve, creating it if it is not there.

    python openobserve/push_dashboard.py openobserve/chronicle.dashboard.json

Matching is by title, so running this twice updates one dashboard rather than creating two.
Creating rather than failing matters because dashboards live in the OpenObserve volume: a
`docker compose down -v` takes them with it, and this is how they come back.

The dashboard in the browser is a copy, not the source. Anything edited there is overwritten the
next time this runs -- edit the file.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import oo_api  # noqa: E402


def push(dashboard: dict) -> int:
    ok, listing = oo_api.api("GET", "/dashboards?folder=default")
    if not ok:
        print("could not list dashboards: %s" % listing, file=sys.stderr)
        return 2

    title = dashboard["title"]
    dashboard_id = None
    for entry in listing.get("dashboards", []):
        inner = entry.get("v8") or entry
        if inner.get("title") == title:
            dashboard_id = inner.get("dashboardId")

    if not dashboard_id:
        # OpenObserve assigns the id on create, so the one in the file is dropped.
        fresh = dict(dashboard)
        fresh.pop("dashboardId", None)
        ok, created = oo_api.api("POST", "/dashboards?folder=default", fresh)
        if not ok:
            print("could not create the dashboard: %s" % created, file=sys.stderr)
            return 2
        inner = created.get("v8") or created
        print("created %r (dashboard %s)" % (title, inner.get("dashboardId")))
        return 0

    # The hash is a concurrency check: OpenObserve rejects a PUT carrying a stale one, which is
    # what stops this from silently discarding an edit somebody made in the UI meanwhile.
    ok, live = oo_api.api("GET", "/dashboards/%s?folder=default" % dashboard_id)
    if not ok:
        print("could not read the live dashboard: %s" % live, file=sys.stderr)
        return 2
    dashboard["dashboardId"] = dashboard_id
    ok, result = oo_api.api(
      "PUT", "/dashboards/%s?folder=default&hash=%s" % (dashboard_id, live["hash"]), dashboard
    )
    if not ok:
        print("push failed: %s" % result, file=sys.stderr)
        return 2
    print("updated %r (dashboard %s)" % (title, dashboard_id))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dashboard")
    args = parser.parse_args(argv)

    _, dashboard = oo_api.load_dashboard(args.dashboard)
    tabs = dashboard.get("tabs") or []
    print("%s -- %d tabs, %d panels" % (
        args.dashboard, len(tabs), sum(len(tab.get("panels") or []) for tab in tabs)))
    return push(dashboard)


if __name__ == "__main__":
    sys.exit(main())
