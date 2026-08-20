from __future__ import annotations

"""Unified backend usage model shared by VS Code chat data and CLI data.

Both the VS Code Copilot Chat debug-log pipeline (`per_chat_calculations.py` /
`global_calculations.py`, producing `app_data["sessions"]`) and the GitHub
Copilot CLI local database pipeline (`cli_usage.py`, producing
`app_data["cli"]`) describe "a model call that cost some tokens/dollars", but
in incompatible shapes. This module normalizes both into one canonical
record so the two can be compared, merged, and bucketed by day/month/model/
repo/source without the frontend needing to know about either source's raw
shape.

Canonical record shape (see `records_from_chat_sessions` / `records_from_cli`):

    {
      "ts": int,              # epoch millis of the model call
      "source": "chat" | "cli",
      "sessionId": str,
      "model": str,
      "host": str,            # source_ip / cache shard for chat; local host for cli
      "repository": str | None,
      "branch": str | None,
      "attributed": {"input": float, "cached": float, "uncached": float, "output": float, "cost": float},
      "billed":     {"input": float, "cached": float, "uncached": float, "output": float, "cost": float},
      "premiumRequests": float,
    }

Identity / host bucketing
--------------------------
`host` is the single canonical identity field for "which developer/host
generated this usage" - it's what `unified.byHost` groups on. Chat records
use `session.source_ip` (the cache-shard name stamped by
`compact_cache.normalize_session_identity`, which also builds the
`shard:session_id` composite used as the session's own `id`); CLI records
use the fixed local-host label `"cli-local"` (CLI's `session-store.db` is
never merged across machines the way chat debug-logs are via remote-sync,
so there is no cross-host CLI identity to distinguish). Every `host` value
is passed through `normalize_host_id()`, which collapses missing/blank
values and near-duplicate "unknown" spellings (`""`, `None`, `"unknown"`,
`"unknown-ip"`, ...) into one bucket, `UNKNOWN_HOST` ("unknown-host"),
instead of letting them fragment into several near-identical `byHost` rows.

Granularity notes
------------------
- Chat records are built **per model call** (one record per `kind == "chat"`
  event inside `session["events"]`), using the event's own precomputed
  `attribution_tokens` (prompt-growth attributed) and `billed_tokens` (raw
  per-call billed) blocks - both already in the exact block shape above via
  `model_pricing.calculate_cost`. If a session has no `events` list (e.g. a
  compacted/cache-preview session with events stripped), this module falls
  back to **one record per session**, built from the session's aggregate
  `totals` / `billed_totals` and its own timestamp. This fallback is
  necessarily coarser than per-call and is the only case where a single
  record can represent multiple underlying model calls.
- CLI records are built **per session+model bucket**
  (`session["modelBreakdown"]` entries in `app_data["cli"]["sessions"]`),
  because `cli_usage.py` only aggregates per-model-call *totals* per session,
  not a raw per-call log. The CLI has exactly one token accounting (no
  prompt-growth attribution concept), so `attributed` and `billed` are
  populated **identically** for CLI records. This is intentional and must
  never be treated as double-counting: only one of the two blocks should
  ever be summed at a time by a consumer, exactly like for chat records.
"""

import collections
from datetime import datetime
from typing import Any

from model_pricing import get_pricing
from premium_requests import get_multiplier

_EMPTY_BLOCK = {"input": 0.0, "cached": 0.0, "uncached": 0.0, "output": 0.0, "cost": 0.0}


def _block(source: dict[str, Any] | None) -> dict[str, float]:
    source = source or {}
    return {
        "input": float(source.get("input", 0.0) or 0.0),
        "cached": float(source.get("cached", 0.0) or 0.0),
        "uncached": float(source.get("uncached", 0.0) or 0.0),
        "output": float(source.get("output", 0.0) or 0.0),
        "cost": float(source.get("cost", 0.0) or 0.0),
    }


def _add_block(target: dict[str, float], source: dict[str, Any], scale: float = 1.0) -> None:
    for key in ("input", "cached", "uncached", "output", "cost"):
        target[key] = target.get(key, 0.0) + float(source.get(key, 0.0) or 0.0) * scale


def month_key_ms(ts_ms: float | int | None) -> str | None:
    """Same format as `global_calculations.month_key_from_timestamp` (%Y-%m)."""
    if not ts_ms:
        return None
    try:
        return datetime.fromtimestamp(float(ts_ms) / 1000.0).strftime("%Y-%m")
    except Exception:
        return None


# Canonical, stable identity field for "which developer/host generated this
# usage" - the single source of truth `unified.byHost` (and the records
# feeding it) key off. Any falsy value or one of these near-duplicate
# unknown-ish spellings collapses into one bucket, `UNKNOWN_HOST`, instead of
# silently splitting across `""`, `None`, `"unknown"`, `"unknown-ip"`, etc.
UNKNOWN_HOST = "unknown-host"
_UNKNOWN_HOST_SPELLINGS = {"", "unknown", "unknown-ip", "unknown-host", "none", "null"}


def normalize_host_id(value: str | None) -> str:
    """Collapse missing/near-duplicate "unknown host" spellings into `UNKNOWN_HOST`."""
    text = str(value if value is not None else "").strip()
    if text.lower() in _UNKNOWN_HOST_SPELLINGS:
        return UNKNOWN_HOST
    return text


def day_key_ms(ts_ms: float | int | None) -> str | None:
    if not ts_ms:
        return None
    try:
        return datetime.fromtimestamp(float(ts_ms) / 1000.0).strftime("%Y-%m-%d")
    except Exception:
        return None


def _premium_requests_for_call(model_name: str | None, calls: float = 1.0, multipliers: dict[str, float] | None = None) -> float:
    return get_multiplier(model_name, multipliers) * float(calls or 0.0)


def records_from_chat_sessions(
    sessions: list[dict[str, Any]] | None,
    multipliers: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Build canonical usage records from `app_data["sessions"]` (VS Code chat).

    `multipliers` optionally overrides the default premium-request multiplier
    table (see `premium_requests.load_config`); when omitted, the built-in
    `premium_requests.MULTIPLIERS` defaults are used.
    """
    records: list[dict[str, Any]] = []
    for session in sessions or []:
        session_id = str(session.get("id") or "")
        host = normalize_host_id(session.get("source_ip"))
        repository = session.get("repository")
        branch = session.get("branch")
        events = session.get("events")

        chat_events = [event for event in events if isinstance(event, dict) and event.get("kind") == "chat"] if isinstance(events, list) else []

        if chat_events:
            for event in chat_events:
                model_name = str(event.get("model") or "unknown")
                ts = event.get("ts") or session.get("timestamp") or 0
                attributed = _block(event.get("attribution_tokens"))
                billed = _block(event.get("billed_tokens"))
                records.append({
                    "ts": int(ts or 0),
                    "source": "chat",
                    "sessionId": session_id,
                    "model": model_name,
                    "host": host,
                    "repository": repository,
                    "branch": branch,
                    "attributed": attributed,
                    "billed": billed,
                    "premiumRequests": _premium_requests_for_call(model_name, 1.0, multipliers),
                })
        else:
            # Fallback: no per-call events available (e.g. compacted session
            # preview). Use the session-level aggregate as a single record.
            model_name = str(session.get("model") or (session.get("model_names") or ["unknown"])[0] or "unknown")
            ts = session.get("timestamp") or 0
            attributed = _block(session.get("totals"))
            billed = _block(session.get("billed_totals"))
            chat_count = float(session.get("chat_count", 0) or 0) or 1.0
            records.append({
                "ts": int(ts or 0),
                "source": "chat",
                "sessionId": session_id,
                "model": model_name,
                "host": host,
                "repository": repository,
                "branch": branch,
                "attributed": attributed,
                "billed": billed,
                "premiumRequests": _premium_requests_for_call(model_name, chat_count, multipliers),
            })
    return records


def records_from_cli(
    cli_data: dict[str, Any] | None,
    multipliers: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Build canonical usage records from `app_data["cli"]`.

    CLI sessions only carry per-session+model aggregate totals (see
    `cli_usage.py::build_cli_dashboard_data`), so one record is emitted per
    `modelBreakdown` entry per session. `attributed` and `billed` are
    populated identically since the CLI has no prompt-growth attribution
    concept - only one raw billed total per model call bucket.
    """
    records: list[dict[str, Any]] = []
    if not cli_data or not cli_data.get("available"):
        return records

    for session in cli_data.get("sessions", []) or []:
        session_id = str(session.get("id") or "")
        host = normalize_host_id("cli-local")
        repository = session.get("repository")
        branch = session.get("branch")
        ts = session.get("lastActivity") or session.get("updatedAt") or session.get("createdAt") or 0
        breakdown = session.get("modelBreakdown") or []
        if not breakdown:
            continue
        for model_row in breakdown:
            model_name = str(model_row.get("model") or "unknown")
            calls = float(model_row.get("calls", 0) or 0)
            block = {
                "input": float(model_row.get("input", 0.0) or 0.0),
                "cached": float(model_row.get("cached", 0.0) or 0.0),
                "uncached": max(0.0, float(model_row.get("input", 0.0) or 0.0) - float(model_row.get("cached", 0.0) or 0.0)),
                "output": float(model_row.get("output", 0.0) or 0.0),
                "cost": float(model_row.get("cost", 0.0) or 0.0),
            }
            records.append({
                "ts": int(ts or 0),
                "source": "cli",
                "sessionId": session_id,
                "model": model_name,
                "host": host,
                "repository": repository,
                "branch": branch,
                # Attributed == billed for CLI: same raw totals, no double-count.
                "attributed": dict(block),
                "billed": dict(block),
                "premiumRequests": _premium_requests_for_call(model_name, calls, multipliers),
            })
    return records


def filter_records(
    records: list[dict[str, Any]],
    start_ms: float | int | None = None,
    end_ms: float | int | None = None,
    source: str | None = None,
) -> list[dict[str, Any]]:
    """Filter canonical records by an inclusive [start_ms, end_ms] range and/or source."""
    out = []
    for record in records or []:
        ts = record.get("ts") or 0
        if start_ms is not None and ts < start_ms:
            continue
        if end_ms is not None and ts > end_ms:
            continue
        if source is not None and record.get("source") != source:
            continue
        out.append(record)
    return out


def _new_bucket() -> dict[str, Any]:
    return {
        "attributed": dict(_EMPTY_BLOCK),
        "billed": dict(_EMPTY_BLOCK),
        "premiumRequests": 0.0,
        "callCount": 0,
        "sessionIds": set(),
    }


def _finalize_bucket(key_name: str, key_value: str, bucket: dict[str, Any], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    out = {
        key_name: key_value,
        "attributed": bucket["attributed"],
        "billed": bucket["billed"],
        "premiumRequests": bucket["premiumRequests"],
        "callCount": bucket["callCount"],
        "sessionCount": len(bucket["sessionIds"]),
    }
    if extra:
        out.update(extra)
    return out


def build_unified(records: list[dict[str, Any]] | None, now_ms: float | int | None = None) -> dict[str, Any]:
    """Aggregate canonical usage records into daily/monthly/model/repo/source/host views.

    Every aggregate row carries both `attributed` and `billed` token/cost
    blocks so a frontend attributed/billed toggle can switch without a
    server round-trip.
    """
    records = records or []

    daily: dict[str, dict[str, Any]] = collections.defaultdict(_new_bucket)
    daily_by_source: dict[str, dict[str, dict[str, Any]]] = collections.defaultdict(lambda: collections.defaultdict(_new_bucket))
    monthly: dict[str, dict[str, Any]] = collections.defaultdict(_new_bucket)
    monthly_by_source: dict[str, dict[str, dict[str, Any]]] = collections.defaultdict(lambda: collections.defaultdict(_new_bucket))
    by_model: dict[str, dict[str, Any]] = collections.defaultdict(_new_bucket)
    by_repo: dict[str, dict[str, Any]] = collections.defaultdict(_new_bucket)
    by_source: dict[str, dict[str, Any]] = collections.defaultdict(_new_bucket)
    by_host: dict[str, dict[str, Any]] = collections.defaultdict(_new_bucket)
    totals = _new_bucket()

    first_ts = None
    last_ts = None

    for record in records:
        ts = record.get("ts") or 0
        source = str(record.get("source") or "unknown")
        model = str(record.get("model") or "unknown")
        repo = record.get("repository") or "unknown"
        host = normalize_host_id(record.get("host"))
        session_id = str(record.get("sessionId") or "")
        premium = float(record.get("premiumRequests", 0.0) or 0.0)
        attributed = record.get("attributed") or _EMPTY_BLOCK
        billed = record.get("billed") or _EMPTY_BLOCK

        if ts:
            first_ts = ts if first_ts is None else min(first_ts, ts)
            last_ts = ts if last_ts is None else max(last_ts, ts)

        day_key = day_key_ms(ts)
        month_key = month_key_ms(ts)

        for bucket_map, key in ((daily, day_key), (monthly, month_key)):
            if key is None:
                continue
            bucket = bucket_map[key]
            _add_block(bucket["attributed"], attributed)
            _add_block(bucket["billed"], billed)
            bucket["premiumRequests"] += premium
            bucket["callCount"] += 1
            bucket["sessionIds"].add(session_id)

        if day_key is not None:
            src_bucket = daily_by_source[day_key][source]
            _add_block(src_bucket["attributed"], attributed)
            _add_block(src_bucket["billed"], billed)
            src_bucket["premiumRequests"] += premium
            src_bucket["callCount"] += 1
            src_bucket["sessionIds"].add(session_id)
        if month_key is not None:
            src_bucket = monthly_by_source[month_key][source]
            _add_block(src_bucket["attributed"], attributed)
            _add_block(src_bucket["billed"], billed)
            src_bucket["premiumRequests"] += premium
            src_bucket["callCount"] += 1
            src_bucket["sessionIds"].add(session_id)

        for bucket_map, key in (
            (by_model, model),
            (by_repo, repo),
            (by_source, source),
            (by_host, host),
        ):
            bucket = bucket_map[key]
            _add_block(bucket["attributed"], attributed)
            _add_block(bucket["billed"], billed)
            bucket["premiumRequests"] += premium
            bucket["callCount"] += 1
            bucket["sessionIds"].add(session_id)

        _add_block(totals["attributed"], attributed)
        _add_block(totals["billed"], billed)
        totals["premiumRequests"] += premium
        totals["callCount"] += 1
        totals["sessionIds"].add(session_id)

    def _sorted_rows(bucket_map: dict[str, dict[str, Any]], key_name: str, use_billed: bool = True) -> list[dict[str, Any]]:
        rows = [_finalize_bucket(key_name, key, bucket) for key, bucket in bucket_map.items()]
        rows.sort(key=lambda row: row["billed"]["cost"] if use_billed else row["attributed"]["cost"], reverse=True)
        return rows

    daily_rows = []
    for day_key in sorted(daily.keys()):
        bucket = daily[day_key]
        by_src = {
            src: _finalize_bucket("source", src, src_bucket)
            for src, src_bucket in daily_by_source.get(day_key, {}).items()
        }
        row = _finalize_bucket("dayKey", day_key, bucket, extra={"bySource": by_src})
        daily_rows.append(row)

    monthly_rows = []
    for month_key in sorted(monthly.keys()):
        bucket = monthly[month_key]
        by_src = {
            src: _finalize_bucket("source", src, src_bucket)
            for src, src_bucket in monthly_by_source.get(month_key, {}).items()
        }
        row = _finalize_bucket("monthKey", month_key, bucket, extra={"bySource": by_src})
        monthly_rows.append(row)

    return {
        "daily": daily_rows,
        "monthly": monthly_rows,
        "byModel": _sorted_rows(by_model, "model"),
        "byRepo": _sorted_rows(by_repo, "repository"),
        "bySource": _sorted_rows(by_source, "source"),
        "byHost": _sorted_rows(by_host, "host"),
        "totals": _finalize_bucket("total", "total", totals),
        "range": {"firstTs": first_ts, "lastTs": last_ts},
    }
