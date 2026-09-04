#!/usr/bin/env python3
"""What the chronicle export knows, rendered for the dashboard's Chronicle tab.

`chronicle_export.py` ships the Copilot CLI's session store into the
`copilot_chronicle_*` streams and prints its result to stderr. Two things it
knows never reached the HTML:

  * how far each stream has been shipped, and how much is still waiting. The
    watermarks in `~/.copilot-dashboard/chronicle_state.json` answer "did the
    export actually run?", which until now meant reading a JSON file by hand;
  * the per-token-type credit split `cost_split()` derives from GitHub's own
    price table for each call (`token_details_json`). The CLI tab shows what a
    call cost; only the chronicle rows say what it was spent ON, and what the
    prompt cache saved by not re-billing the same context at the input rate.

Both are read from the same local store the rest of the dashboard reads, so
this needs no network and works whether or not OpenObserve is reachable. The
rows are built by calling `build_chronicle_rows` itself rather than by
re-deriving the arithmetic here: the credit split is exact because it comes
from GitHub's rates, and a second implementation of it would be a second thing
to keep exact.

THE DRIFT CHECK IS THE POINT OF THE CROSS-FOOT
----------------------------------------------
`copilot_chronicle_costs` re-prices each call from its rate table and
`copilot_chronicle_usage` reports the charge GitHub recorded for it, so the two
sums must agree. `chronicle_export.cost_split`'s docstring states the invariant
and what a violation means: the price table gained a token type the split is
silently dropping, which would understate spend everywhere it is shown. So the
tab cross-foots them and says so when they disagree, rather than quietly
showing a number that is missing a column.
"""
from __future__ import annotations

import datetime as dt
import os
import sqlite3
from typing import Any

from chronicle_export import (
    ADVICE_COLUMNS,
    ADVICE_STREAM,
    JOBS,
    build_chronicle_rows,
    default_state_path,
    endpoint_for,
    load_state,
)

# A thousandth of a credit — the agreement `cost_split` documents as reachable
# across a whole store. Anything larger is a real gap, not float noise.
DRIFT_TOLERANCE_CREDITS = 0.001

_SPLIT_FIELDS = (
    ("credits_input", "creditsInput"),
    ("credits_cache_read", "creditsCacheRead"),
    ("credits_cache_write", "creditsCacheWrite"),
    ("credits_output", "creditsOutput"),
    ("credits_total", "creditsTotal"),
    ("credits_if_no_cache", "creditsIfNoCache"),
    ("credits_cache_saved", "creditsCacheSaved"),
)

REASON_NO_DB = "no_db"
REASON_QUERY_FAILED = "query_failed"


def empty_chronicle_payload(
    db_path: str | None = None,
    reason: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """The shape the UI can always render, so a missing store degrades quietly."""
    return {
        "available": False,
        "reason": reason,
        "error": error,
        "dbPath": db_path or "",
        "statePath": "",
        "streams": [],
        "advice": {"stream": ADVICE_STREAM, "columns": list(ADVICE_COLUMNS), "endpoint": ""},
        "totals": {"shipped": 0, "pending": 0, "rowsInDb": 0, "lastRunAt": None},
        "costs": {"totals": _empty_bucket(), "byModel": [], "byDay": []},
        "drift": {
            "creditsTotal": 0.0,
            "aiCredits": 0.0,
            "difference": 0.0,
            "withinTolerance": True,
            "tolerance": DRIFT_TOLERANCE_CREDITS,
            "callsPriced": 0,
            "callsBilled": 0,
            "callsUnpriced": 0,
            "creditsUnpriced": 0.0,
            "billedTotal": 0.0,
        },
    }


def _empty_bucket() -> dict[str, Any]:
    bucket: dict[str, Any] = {"calls": 0, "callsPriced": 0}
    for _source, key in _SPLIT_FIELDS:
        bucket[key] = 0.0
    return bucket


def _add_split(bucket: dict[str, Any], row: dict[str, Any]) -> None:
    bucket["calls"] += 1
    # A call with no `token_details_json` (older CLI build) carries no split at
    # all. Counting it as priced would make the cache-saving percentages read
    # as if it had contributed a zero, dragging them toward nothing.
    if "credits_total" not in row:
        return
    bucket["callsPriced"] += 1
    for source, key in _SPLIT_FIELDS:
        bucket[key] += float(row.get(source, 0.0) or 0.0)


def _finish_bucket(bucket: dict[str, Any]) -> dict[str, Any]:
    out = dict(bucket)
    for _source, key in _SPLIT_FIELDS:
        out[key] = round(float(out.get(key, 0.0)), 6)
    if_no_cache = out.get("creditsIfNoCache", 0.0)
    out["cacheSavedPercent"] = round((out.get("creditsCacheSaved", 0.0) / if_no_cache) * 100.0, 2) if if_no_cache else 0.0
    return out


def _day_key(stamp_micros: Any) -> str | None:
    """The local calendar day a call was made on.

    Local, not UTC: every other per-day figure on this dashboard is grouped the
    way the developer experienced the day, and two groupings of "today" side by
    side would not add up.
    """
    if not stamp_micros:
        return None
    try:
        return dt.datetime.fromtimestamp(int(stamp_micros) / 1_000_000.0).strftime("%Y-%m-%d")
    except (OverflowError, OSError, ValueError):
        return None


def _open_readonly(db_path: str) -> sqlite3.Connection:
    """Read-only, over the live file including its WAL.

    `chronicle_export.open_copy` snapshots the store first because it is a
    long-running bulk read that must not hold a lock on the file Copilot is
    writing; this is a handful of aggregate queries, so it reads in place the
    same way `cli_usage.build_cli_dashboard_data` does — and reading through
    the WAL matters, since a session that just ended is still only there.
    """
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    return connection


def _stream_status(
    connection: sqlite3.Connection,
    job: dict[str, Any],
    state: dict[str, Any],
    base_url: str | None,
    org: str | None,
    stream_urls: dict[str, str] | None,
) -> dict[str, Any]:
    stream = job["stream"]
    watermark = job["watermark"]
    table = job["table"]
    recorded = state.get(stream) or {}
    last_id = recorded.get("last_id")

    cursor = connection.cursor()
    rows_in_db = int(cursor.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] or 0)
    # Counted, not derived as `max - last_id`: the watermark columns have gaps
    # (deleted rows, and `sessions` uses SQLite's implicit rowid), so
    # subtracting the two would overstate the backlog on a pruned store.
    if last_id is None:
        pending = rows_in_db
    else:
        pending = int(
            cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE {watermark} > ?", (last_id,)).fetchone()[0] or 0
        )

    try:
        endpoint = endpoint_for(stream, base_url=base_url, org=org, stream_urls=stream_urls)
    except Exception:  # noqa: BLE001 - a display string is never worth failing the tab for
        endpoint = ""

    return {
        "stream": stream,
        "table": table,
        "watermarkColumn": watermark,
        "timeColumn": job["time"],
        "lastId": last_id,
        "sentAt": recorded.get("at"),
        "rowsInDb": rows_in_db,
        "shipped": max(rows_in_db - pending, 0),
        "pending": pending,
        "endpoint": endpoint,
        "everShipped": last_id is not None,
    }


def build_chronicle_payload(
    db_path: str | None = None,
    state_path: str | None = None,
    base_url: str | None = None,
    org: str | None = None,
    stream_urls: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Chronicle export status plus the exact credit split, from the local store."""
    resolved_state = state_path or default_state_path()
    if not db_path or not os.path.exists(db_path):
        payload = empty_chronicle_payload(db_path, REASON_NO_DB)
        payload["statePath"] = resolved_state
        return payload

    state = load_state(resolved_state)
    try:
        connection = _open_readonly(db_path)
    except sqlite3.Error as exc:
        payload = empty_chronicle_payload(db_path, REASON_QUERY_FAILED, str(exc))
        payload["statePath"] = resolved_state
        return payload

    try:
        streams = [_stream_status(connection, job, state, base_url, org, stream_urls) for job in JOBS]

        costs_job = next(job for job in JOBS if job["stream"] == "copilot_chronicle_costs")
        usage_job = next(job for job in JOBS if job["stream"] == "copilot_chronicle_usage")
        cost_rows, _highest, _skipped = build_chronicle_rows(connection, costs_job)
        usage_rows, _uhighest, _uskipped = build_chronicle_rows(connection, usage_job)
    finally:
        connection.close()

    totals = _empty_bucket()
    by_model: dict[str, dict[str, Any]] = {}
    by_day: dict[str, dict[str, Any]] = {}
    for row in cost_rows:
        _add_split(totals, row)
        model = str(row.get("model") or "unknown")
        _add_split(by_model.setdefault(model, {**_empty_bucket(), "model": model}), row)
        day = _day_key(row.get("_timestamp"))
        if day:
            _add_split(by_day.setdefault(day, {**_empty_bucket(), "day": day}), row)

    # Cross-foot only the calls that appear on BOTH sides. Both jobs read
    # `assistant_usage_events` with `id` as the watermark, so `chronicle_row_id`
    # identifies the same call in each. A call whose `token_details_json` is
    # missing (older CLI build) is billed but cannot be split, and counting its
    # charge on the billed side alone would report a drift that is really just
    # coverage — the alarm this panel raises has to mean "the split is dropping a
    # token type", or it means nothing.
    priced_ids = {row.get("chronicle_row_id") for row in cost_rows if "credits_total" in row}
    billed_credits = 0.0
    calls_billed = 0
    unpriced_credits = 0.0
    calls_unpriced = 0
    for row in usage_rows:
        credits = float(row.get("ai_credits", 0.0) or 0.0)
        if row.get("chronicle_row_id") in priced_ids:
            billed_credits += credits
            if "ai_credits" in row:
                calls_billed += 1
        else:
            unpriced_credits += credits
            calls_unpriced += 1
    difference = round(totals["creditsTotal"] - billed_credits, 6)

    payload = empty_chronicle_payload(db_path)
    payload.update({
        "available": True,
        "reason": None,
        "statePath": resolved_state,
        "streams": streams,
        "advice": {
            "stream": ADVICE_STREAM,
            "columns": list(ADVICE_COLUMNS),
            "endpoint": endpoint_for(ADVICE_STREAM, base_url=base_url, org=org, stream_urls=stream_urls),
        },
        "totals": {
            "shipped": sum(row["shipped"] for row in streams),
            "pending": sum(row["pending"] for row in streams),
            "rowsInDb": sum(row["rowsInDb"] for row in streams),
            "lastRunAt": max((row["sentAt"] for row in streams if row["sentAt"]), default=None),
        },
        "costs": {
            "totals": _finish_bucket(totals),
            "byModel": sorted(
                (_finish_bucket(bucket) for bucket in by_model.values()),
                key=lambda bucket: bucket["creditsTotal"],
                reverse=True,
            ),
            "byDay": sorted((_finish_bucket(bucket) for bucket in by_day.values()), key=lambda bucket: bucket["day"]),
        },
        "drift": {
            "creditsTotal": round(totals["creditsTotal"], 6),
            "aiCredits": round(billed_credits, 6),
            "difference": difference,
            "withinTolerance": abs(difference) <= DRIFT_TOLERANCE_CREDITS,
            "tolerance": DRIFT_TOLERANCE_CREDITS,
            "callsPriced": totals["callsPriced"],
            "callsBilled": calls_billed,
            "callsUnpriced": calls_unpriced,
            "creditsUnpriced": round(unpriced_credits, 6),
            "billedTotal": round(billed_credits + unpriced_credits, 6),
        },
    })
    return payload
