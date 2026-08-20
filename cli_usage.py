from __future__ import annotations

import collections
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

from model_pricing import calculate_cost


def _month_key_from_epoch_ms(ts_ms: float | int | None) -> str | None:
    if not ts_ms:
        return None
    try:
        return datetime.fromtimestamp(float(ts_ms) / 1000.0).strftime("%Y-%m")
    except Exception:
        return None


def _day_key_from_epoch_ms(ts_ms: float | int | None) -> str | None:
    if not ts_ms:
        return None
    try:
        return datetime.fromtimestamp(float(ts_ms) / 1000.0).strftime("%Y-%m-%d")
    except Exception:
        return None


def _build_cli_period_bundle(sessions_subset: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a {"summary", "byModel"} bundle for a subset of CLI sessions_out rows.

    Mirrors the shape of the chat pipeline's period bundles closely enough
    for the CLI tab to support "this month" / "all time" filtering, without
    touching any existing `cli["..."]` key.
    """
    model_totals: dict[str, dict[str, float]] = collections.defaultdict(
        lambda: {"input": 0.0, "output": 0.0, "cached": 0.0, "cacheWrite": 0.0, "calls": 0, "sessionIds": set()}
    )
    total_cost = 0.0
    total_input = 0.0
    total_output = 0.0
    total_cached = 0.0
    total_calls = 0
    total_tool_calls = 0
    file_paths: set[str] = set()

    for session in sessions_subset:
        total_cost += float(session.get("cost", 0.0) or 0.0)
        total_input += float(session.get("input", 0.0) or 0.0)
        total_output += float(session.get("output", 0.0) or 0.0)
        total_cached += float(session.get("cached", 0.0) or 0.0)
        total_calls += int(session.get("callCount", 0) or 0)
        total_tool_calls += sum(int(tool.get("calls", 0) or 0) for tool in session.get("tools", []) or [])
        for file_row in session.get("files", []) or []:
            path = file_row.get("path")
            if path:
                file_paths.add(path)
        for row in session.get("modelBreakdown", []) or []:
            model_name = str(row.get("model") or "unknown")
            bucket = model_totals[model_name]
            bucket["input"] += float(row.get("input", 0.0) or 0.0)
            bucket["output"] += float(row.get("output", 0.0) or 0.0)
            bucket["cached"] += float(row.get("cached", 0.0) or 0.0)
            bucket["cacheWrite"] += float(row.get("cacheWrite", 0.0) or 0.0)
            bucket["calls"] += int(row.get("calls", 0) or 0)
            bucket["sessionIds"].add(session.get("id"))

    by_model = []
    for model_name, bucket in model_totals.items():
        cost_info = calculate_cost(bucket["input"], bucket["output"], bucket["cached"], model_name)
        by_model.append({
            "model": model_name,
            "calls": bucket["calls"],
            "sessionCount": len(bucket["sessionIds"]),
            "input": bucket["input"],
            "uncached": max(0.0, bucket["input"] - bucket["cached"]),
            "cached": bucket["cached"],
            "cacheWrite": bucket["cacheWrite"],
            "output": bucket["output"],
            "cost": cost_info["cost"],
        })
    by_model.sort(key=lambda row: row["cost"], reverse=True)

    return {
        "summary": {
            "sessionCount": len(sessions_subset),
            "callCount": total_calls,
            "totalInput": total_input,
            "totalOutput": total_output,
            "totalCached": total_cached,
            "totalUncached": max(0.0, total_input - total_cached),
            "totalCost": total_cost,
            "fileCount": len(file_paths),
            "toolCallCount": total_tool_calls,
        },
        "byModel": by_model,
    }


def default_cli_db_path() -> str | None:
    """Return the local GitHub Copilot CLI session-store.db path, if it exists."""
    override = os.environ.get("COPILOT_CLI_DB")
    if override:
        return override
    candidate = os.path.join(os.path.expanduser("~"), ".copilot", "session-store.db")
    return candidate if os.path.isfile(candidate) else None


def default_cli_otel_paths() -> list[str]:
    """Return the CLI's OpenTelemetry file-exporter JSONL path(s), if configured.

    The CLI only writes this file when OTel export is enabled (see
    `copilot help monitoring`), typically via the `COPILOT_OTEL_FILE_EXPORTER_PATH`
    environment variable. When present, it carries official OTel GenAI spans
    (chat calls, execute_tool calls) with exact per-call cost/token/duration
    data — a stronger, structured complement to session-store.db.
    """
    override = os.environ.get("COPILOT_OTEL_FILE_EXPORTER_PATH")
    if override and os.path.isfile(override):
        return [override]
    return []


def _otel_timestamp_to_epoch_ms(value: Any) -> float:
    """Convert an OTel [seconds, nanoseconds] timestamp pair to epoch milliseconds."""
    try:
        seconds, nanos = value
        return float(seconds) * 1000 + float(nanos) / 1e6
    except Exception:
        return 0.0


def parse_cli_otel_files(paths: list[str] | None) -> dict[str, Any]:
    """Parse CLI OTel file-exporter JSONL export(s) for `execute_tool` span telemetry.

    Returns {"available", "paths", "tools": [...], "toolsBySession": {session_id: [...]}}.
    Silently skips missing/unreadable files or malformed lines — this is a
    best-effort enrichment layer, not the primary CLI data source.
    """
    global_tools: dict[str, dict[str, Any]] = collections.defaultdict(
        lambda: {"calls": 0, "durationMs": 0.0, "sessionIds": set()}
    )
    tools_by_session: dict[str, dict[str, dict[str, Any]]] = collections.defaultdict(
        lambda: collections.defaultdict(lambda: {"calls": 0, "durationMs": 0.0})
    )
    parsed_any = False
    used_paths: list[str] = []

    for path in paths or []:
        if not path or not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except Exception:
                        continue
                    if entry.get("type") != "span":
                        continue
                    name = str(entry.get("name") or "")
                    if not name.startswith("execute_tool"):
                        continue
                    attrs = entry.get("attributes") or {}
                    tool_name = attrs.get("gen_ai.tool.name") or name[len("execute_tool "):].strip() or "unknown"
                    conversation_id = attrs.get("gen_ai.conversation.id")
                    duration_ms = max(
                        0.0,
                        _otel_timestamp_to_epoch_ms(entry.get("endTime")) - _otel_timestamp_to_epoch_ms(entry.get("startTime")),
                    )
                    parsed_any = True
                    used_paths.append(path)

                    gtotal = global_tools[tool_name]
                    gtotal["calls"] += 1
                    gtotal["durationMs"] += duration_ms
                    if conversation_id:
                        gtotal["sessionIds"].add(conversation_id)
                        sbucket = tools_by_session[conversation_id][tool_name]
                        sbucket["calls"] += 1
                        sbucket["durationMs"] += duration_ms
        except Exception:
            continue

    tools_out = sorted(
        (
            {
                "tool": tool_name,
                "calls": data["calls"],
                "totalDurationMs": data["durationMs"],
                "avgDurationMs": (data["durationMs"] / data["calls"]) if data["calls"] else 0.0,
                "sessionCount": len(data["sessionIds"]),
            }
            for tool_name, data in global_tools.items()
        ),
        key=lambda row: row["calls"],
        reverse=True,
    )

    tools_by_session_out = {
        session_id: sorted(
            (
                {
                    "tool": tool_name,
                    "calls": data["calls"],
                    "totalDurationMs": data["durationMs"],
                    "avgDurationMs": (data["durationMs"] / data["calls"]) if data["calls"] else 0.0,
                }
                for tool_name, data in tools.items()
            ),
            key=lambda row: row["calls"],
            reverse=True,
        )
        for session_id, tools in tools_by_session.items()
    }

    return {
        "available": parsed_any,
        "paths": sorted(set(used_paths)) or [p for p in (paths or []) if p],
        "tools": tools_out,
        "toolsBySession": tools_by_session_out,
    }


def _iso_to_epoch_ms(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).timestamp() * 1000
    except Exception:
        return 0.0


def build_cli_dashboard_data(
    db_path: str | None = None,
    otel_log_paths: list[str] | None = None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Read GitHub Copilot CLI local usage from session-store.db (read-only).

    Returns a JSON-serializable structure independent from the VS Code
    debug-log pipeline: {"available": bool, "dbPath", "sessions": [...],
    "byModel": [...], "tools": [...], "otelAvailable", "summary": {...}}.
    If an OTel JSONL export is available (see `default_cli_otel_paths`), it
    enriches sessions and the summary with real per-tool call telemetry.

    `now_ms` is an optional epoch-milliseconds time-injection seam for the
    "current calendar month" the `periods.monthly` bucket is built from
    (and its label). It defaults to the live wall clock so every existing
    caller is unaffected; tests can pass a frozen `now_ms` instead of relying
    on real-clock-relative fixtures.
    """
    now = datetime.fromtimestamp(float(now_ms) / 1000.0) if now_ms else datetime.now()
    resolved_db_path = db_path or default_cli_db_path()
    if not resolved_db_path or not os.path.isfile(resolved_db_path):
        return {"available": False, "dbPath": resolved_db_path, "sessions": [], "byModel": [], "files": [], "tools": [], "otelAvailable": False, "otelPaths": [], "summary": {}, "periods": {"default": "monthly", "labels": {}, "allTime": {"summary": {}, "byModel": []}, "monthly": {"monthKey": None, "summary": {}, "byModel": []}}}


    try:
        # Read-only URI connection avoids taking a write lock on the live CLI DB.
        con = sqlite3.connect(f"file:{resolved_db_path}?mode=ro", uri=True, timeout=5)
    except Exception:
        try:
            con = sqlite3.connect(resolved_db_path, timeout=5)
        except Exception:
            return {"available": False, "dbPath": resolved_db_path, "sessions": [], "byModel": [], "files": [], "tools": [], "otelAvailable": False, "otelPaths": [], "summary": {}, "periods": {"default": "monthly", "labels": {}, "allTime": {"summary": {}, "byModel": []}, "monthly": {"monthKey": None, "summary": {}, "byModel": []}}}

    try:
        cur = con.cursor()

        cur.execute("SELECT id, cwd, repository, branch, summary, created_at, updated_at FROM sessions")
        session_rows = cur.fetchall()
        session_meta: dict[str, dict[str, Any]] = {}
        for session_id, cwd, repository, branch, summary, created_at, updated_at in session_rows:
            session_meta[session_id] = {
                "id": session_id,
                "cwd": cwd,
                "repository": repository,
                "branch": branch,
                "summary": summary,
                "createdAt": _iso_to_epoch_ms(created_at),
                "updatedAt": _iso_to_epoch_ms(updated_at),
            }

        cur.execute(
            "SELECT session_id, turn_index, model, input_tokens, output_tokens, "
            "cache_read_tokens, cache_write_tokens, reasoning_tokens, duration_ms, created_at "
            "FROM assistant_usage_events"
        )
        event_rows = cur.fetchall()

        cur.execute("SELECT session_id, MAX(turn_index) FROM turns GROUP BY session_id")
        turn_counts = {session_id: (max_turn or 0) + 1 for session_id, max_turn in cur.fetchall()}

        cur.execute("SELECT session_id, file_path, tool_name, first_seen_at FROM session_files")
        file_rows = cur.fetchall()

        cur.execute(
            "SELECT session_id, turn_index, user_message, assistant_response, timestamp "
            "FROM turns ORDER BY session_id, turn_index"
        )
        turn_rows = cur.fetchall()
    finally:
        con.close()

    resolved_otel_paths = otel_log_paths if otel_log_paths is not None else default_cli_otel_paths()
    otel_data = parse_cli_otel_files(resolved_otel_paths)

    files_by_session: dict[str, dict[str, dict[str, Any]]] = collections.defaultdict(
        lambda: collections.defaultdict(lambda: {"path": "", "created": 0, "edited": 0, "lastTouched": 0.0})
    )
    for session_id, file_path, tool_name, first_seen_at in file_rows:
        session_entry = files_by_session[session_id][file_path]
        session_entry["path"] = file_path
        if tool_name == "create":
            session_entry["created"] += 1
        else:
            session_entry["edited"] += 1
        session_entry["lastTouched"] = max(session_entry["lastTouched"], _iso_to_epoch_ms(first_seen_at))

    files_by_session_out = {
        session_id: sorted(
            (
                {
                    "path": entry["path"],
                    "created": entry["created"],
                    "edited": entry["edited"],
                    "touches": entry["created"] + entry["edited"],
                    "lastTouched": entry["lastTouched"],
                }
                for entry in files.values()
            ),
            key=lambda row: row["touches"],
            reverse=True,
        )
        for session_id, files in files_by_session.items()
    }

    _TURN_PREVIEW_LIMIT = 800
    turns_by_session: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for session_id, turn_index, user_message, assistant_response, timestamp in turn_rows:
        user_text = str(user_message or "")
        assistant_text = str(assistant_response or "")
        turns_by_session[session_id].append({
            "turnIndex": turn_index,
            "timestamp": _iso_to_epoch_ms(timestamp),
            "userMessage": user_text[:_TURN_PREVIEW_LIMIT],
            "userMessageTruncated": len(user_text) > _TURN_PREVIEW_LIMIT,
            "assistantResponse": assistant_text[:_TURN_PREVIEW_LIMIT],
            "assistantResponseTruncated": len(assistant_text) > _TURN_PREVIEW_LIMIT,
        })

    per_session: dict[str, dict[str, Any]] = {}
    per_session_model: dict[tuple[str, str], dict[str, float]] = collections.defaultdict(
        lambda: {"input": 0.0, "output": 0.0, "cached": 0.0, "cacheWrite": 0.0, "reasoning": 0.0, "calls": 0, "durationMs": 0.0}
    )
    model_totals: dict[str, dict[str, float]] = collections.defaultdict(
        lambda: {"input": 0.0, "output": 0.0, "cached": 0.0, "cacheWrite": 0.0, "reasoning": 0.0, "calls": 0, "sessionIds": set()}
    )

    for session_id, turn_index, model, input_tokens, output_tokens, cache_read, cache_write, reasoning, duration_ms, created_at in event_rows:
        model_name = model or "unknown"
        key = (session_id, model_name)
        bucket = per_session_model[key]
        bucket["input"] += float(input_tokens or 0)
        bucket["output"] += float(output_tokens or 0)
        bucket["cached"] += float(cache_read or 0)
        bucket["cacheWrite"] += float(cache_write or 0)
        bucket["reasoning"] += float(reasoning or 0)
        bucket["calls"] += 1
        bucket["durationMs"] += float(duration_ms or 0)

        entry = per_session.setdefault(session_id, {
            "id": session_id,
            "models": set(),
            "calls": 0,
            "lastActivity": 0.0,
        })
        entry["models"].add(model_name)
        entry["calls"] += 1
        entry["lastActivity"] = max(entry["lastActivity"], _iso_to_epoch_ms(created_at))

        mtotal = model_totals[model_name]
        mtotal["input"] += float(input_tokens or 0)
        mtotal["output"] += float(output_tokens or 0)
        mtotal["cached"] += float(cache_read or 0)
        mtotal["cacheWrite"] += float(cache_write or 0)
        mtotal["reasoning"] += float(reasoning or 0)
        mtotal["calls"] += 1
        mtotal["sessionIds"].add(session_id)

    sessions_out: list[dict[str, Any]] = []
    total_cost = 0.0
    total_input = 0.0
    total_output = 0.0
    total_cached = 0.0

    for session_id, entry in per_session.items():
        meta = session_meta.get(session_id, {})
        session_cost = 0.0
        session_input = 0.0
        session_output = 0.0
        session_cached = 0.0
        model_breakdown = []
        for model_name in entry["models"]:
            bucket = per_session_model[(session_id, model_name)]
            cost_info = calculate_cost(bucket["input"], bucket["output"], bucket["cached"], model_name)
            session_cost += cost_info["cost"]
            session_input += bucket["input"]
            session_output += bucket["output"]
            session_cached += bucket["cached"]
            model_breakdown.append({
                "model": model_name,
                "calls": bucket["calls"],
                "input": bucket["input"],
                "output": bucket["output"],
                "cached": bucket["cached"],
                "cacheWrite": bucket["cacheWrite"],
                "cost": cost_info["cost"],
            })

        total_cost += session_cost
        total_input += session_input
        total_output += session_output
        total_cached += session_cached

        sessions_out.append({
            "id": session_id,
            "cwd": meta.get("cwd"),
            "repository": meta.get("repository"),
            "branch": meta.get("branch"),
            "summary": meta.get("summary"),
            "createdAt": meta.get("createdAt", 0.0),
            "updatedAt": meta.get("updatedAt", 0.0),
            "lastActivity": entry["lastActivity"] or meta.get("updatedAt", 0.0),
            "monthKey": _month_key_from_epoch_ms(entry["lastActivity"] or meta.get("updatedAt", 0.0)),
            "dayKey": _day_key_from_epoch_ms(entry["lastActivity"] or meta.get("updatedAt", 0.0)),
            "turnCount": turn_counts.get(session_id, 0),
            "callCount": entry["calls"],
            "models": sorted(entry["models"]),
            "modelBreakdown": sorted(model_breakdown, key=lambda row: row["cost"], reverse=True),
            "input": session_input,
            "output": session_output,
            "cached": session_cached,
            "uncached": max(0.0, session_input - session_cached),
            "cost": session_cost,
            "turns": turns_by_session.get(session_id, []),
            "tools": otel_data["toolsBySession"].get(session_id, []),
            "files": files_by_session_out.get(session_id, []),
        })

    sessions_out.sort(key=lambda row: row["lastActivity"], reverse=True)

    by_model = []
    for model_name, mtotal in model_totals.items():
        cost_info = calculate_cost(mtotal["input"], mtotal["output"], mtotal["cached"], model_name)
        by_model.append({
            "model": model_name,
            "calls": mtotal["calls"],
            "sessionCount": len(mtotal["sessionIds"]),
            "input": mtotal["input"],
            "uncached": max(0.0, mtotal["input"] - mtotal["cached"]),
            "cached": mtotal["cached"],
            "cacheWrite": mtotal["cacheWrite"],
            "output": mtotal["output"],
            "cost": cost_info["cost"],
        })
    by_model.sort(key=lambda row: row["cost"], reverse=True)

    file_stats: dict[str, dict[str, Any]] = collections.defaultdict(
        lambda: {"path": "", "created": 0, "edited": 0, "sessionIds": set(), "lastTouched": 0.0}
    )
    for session_id, file_path, tool_name, first_seen_at in file_rows:
        entry = file_stats[file_path]
        entry["path"] = file_path
        if tool_name == "create":
            entry["created"] += 1
        else:
            entry["edited"] += 1
        entry["sessionIds"].add(session_id)
        entry["lastTouched"] = max(entry["lastTouched"], _iso_to_epoch_ms(first_seen_at))

    files_out = sorted(
        (
            {
                "path": entry["path"],
                "created": entry["created"],
                "edited": entry["edited"],
                "touches": entry["created"] + entry["edited"],
                "sessionCount": len(entry["sessionIds"]),
                "lastTouched": entry["lastTouched"],
            }
            for entry in file_stats.values()
        ),
        key=lambda row: row["touches"],
        reverse=True,
    )

    return {
        "available": True,
        "dbPath": resolved_db_path,
        "sessions": sessions_out,
        "byModel": by_model,
        "files": files_out,
        "tools": otel_data["tools"],
        "otelAvailable": otel_data["available"],
        "otelPaths": otel_data["paths"],
        "summary": {
            "sessionCount": len(sessions_out),
            "callCount": len(event_rows),
            "totalInput": total_input,
            "totalOutput": total_output,
            "totalCached": total_cached,
            "totalUncached": max(0.0, total_input - total_cached),
            "totalCost": total_cost,
            "fileCount": len(files_out),
            "toolCallCount": sum(row["calls"] for row in otel_data["tools"]),
        },
        "periods": {
            "default": "monthly",
            "labels": {
                "allTime": "All time",
                "monthly": now.strftime("%B %Y"),
            },
            "allTime": _build_cli_period_bundle(sessions_out),
            "monthly": {
                "monthKey": now.strftime("%Y-%m"),
                **_build_cli_period_bundle(
                    [s for s in sessions_out if s.get("monthKey") == now.strftime("%Y-%m")]
                ),
            },
        },
    }
