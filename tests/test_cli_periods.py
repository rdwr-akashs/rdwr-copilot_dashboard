"""Tests for the cli["periods"] block added to cli_usage.build_cli_dashboard_data().

`monthly` is defined against the real current calendar month (there is no
`now_ms` injection point in cli_usage.py), so this fixture builds session
timestamps relative to `datetime.now()` at test time rather than hardcoding
dates, keeping the test correct regardless of which day it runs on.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from cli_usage import build_cli_dashboard_data


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_db(tmp_path):
    now = datetime.now()
    # Use day=15 for both anchors (safe for every month, and far from
    # midnight) to avoid a local/UTC round-trip in `_iso_to_epoch_ms`
    # accidentally shifting a date across a month boundary.
    current_month_ts = now.replace(day=15, hour=10, minute=0, second=0, microsecond=0)
    previous_month_ts = (now.replace(day=1) - timedelta(days=1)).replace(day=15, hour=10, minute=0, second=0, microsecond=0)

    db_path = tmp_path / "session-store.db"
    con = sqlite3.connect(str(db_path))
    try:
        cur = con.cursor()
        cur.execute(
            "CREATE TABLE sessions (id TEXT PRIMARY KEY, cwd TEXT, repository TEXT, branch TEXT, "
            "summary TEXT, created_at TEXT, updated_at TEXT)"
        )
        cur.execute(
            "CREATE TABLE assistant_usage_events (session_id TEXT, turn_index INTEGER, model TEXT, "
            "input_tokens INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER, "
            "cache_write_tokens INTEGER, reasoning_tokens INTEGER, duration_ms INTEGER, created_at TEXT)"
        )
        cur.execute(
            "CREATE TABLE turns (session_id TEXT, turn_index INTEGER, user_message TEXT, "
            "assistant_response TEXT, timestamp TEXT)"
        )
        cur.execute(
            "CREATE TABLE session_files (session_id TEXT, file_path TEXT, tool_name TEXT, first_seen_at TEXT)"
        )

        sessions = [
            ("current-session", "/repo/a", "org/repo-a", "main", "Current month work", _iso(current_month_ts), _iso(current_month_ts)),
            ("previous-session", "/repo/b", "org/repo-b", "main", "Previous month work", _iso(previous_month_ts), _iso(previous_month_ts)),
        ]
        cur.executemany(
            "INSERT INTO sessions (id, cwd, repository, branch, summary, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            sessions,
        )

        events = [
            ("current-session", 0, "gpt-5.4", 1000, 200, 100, 0, 0, 1000, _iso(current_month_ts)),
            ("current-session", 1, "gpt-5.4", 1500, 300, 200, 0, 0, 1200, _iso(current_month_ts)),
            ("previous-session", 0, "claude-sonnet-4.5", 2000, 400, 500, 0, 0, 1500, _iso(previous_month_ts)),
        ]
        cur.executemany(
            "INSERT INTO assistant_usage_events (session_id, turn_index, model, input_tokens, output_tokens, "
            "cache_read_tokens, cache_write_tokens, reasoning_tokens, duration_ms, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            events,
        )

        turns = [
            ("current-session", 0, "hi", "hello", _iso(current_month_ts)),
            ("previous-session", 0, "hi", "hello", _iso(previous_month_ts)),
        ]
        cur.executemany(
            "INSERT INTO turns (session_id, turn_index, user_message, assistant_response, timestamp) VALUES (?, ?, ?, ?, ?)",
            turns,
        )

        session_files = [
            ("current-session", "a.py", "edit", _iso(current_month_ts)),
            ("previous-session", "b.py", "edit", _iso(previous_month_ts)),
        ]
        cur.executemany(
            "INSERT INTO session_files (session_id, file_path, tool_name, first_seen_at) VALUES (?, ?, ?, ?)",
            session_files,
        )
        con.commit()
    finally:
        con.close()

    return str(db_path)


def test_periods_block_present_with_expected_shape(tmp_path):
    db_path = _build_db(tmp_path)
    data = build_cli_dashboard_data(db_path, otel_log_paths=[])
    periods = data["periods"]

    assert periods["default"] == "monthly"
    assert "allTime" in periods and "monthly" in periods
    assert periods["monthly"]["monthKey"] == datetime.now().strftime("%Y-%m")
    for bundle in (periods["allTime"], periods["monthly"]):
        assert "summary" in bundle
        assert "byModel" in bundle


def test_monthly_period_contains_only_current_month_sessions(tmp_path):
    db_path = _build_db(tmp_path)
    data = build_cli_dashboard_data(db_path, otel_log_paths=[])
    monthly_summary = data["periods"]["monthly"]["summary"]
    all_time_summary = data["periods"]["allTime"]["summary"]

    # Only "current-session" (2 calls) falls in the current calendar month.
    assert monthly_summary["sessionCount"] == 1
    assert monthly_summary["callCount"] == 2
    # Both sessions (3 calls total) are in allTime.
    assert all_time_summary["sessionCount"] == 2
    assert all_time_summary["callCount"] == 3


def test_monthly_by_model_covers_only_current_month_model(tmp_path):
    db_path = _build_db(tmp_path)
    data = build_cli_dashboard_data(db_path, otel_log_paths=[])
    monthly_models = {row["model"] for row in data["periods"]["monthly"]["byModel"]}
    all_time_models = {row["model"] for row in data["periods"]["allTime"]["byModel"]}

    assert monthly_models == {"gpt-5.4"}
    assert all_time_models == {"gpt-5.4", "claude-sonnet-4.5"}


def test_monthly_totals_never_exceed_all_time_totals(tmp_path):
    db_path = _build_db(tmp_path)
    data = build_cli_dashboard_data(db_path, otel_log_paths=[])
    monthly_summary = data["periods"]["monthly"]["summary"]
    all_time_summary = data["periods"]["allTime"]["summary"]

    for key in ("sessionCount", "callCount", "totalInput", "totalOutput", "totalCached", "totalCost", "fileCount"):
        assert monthly_summary[key] <= all_time_summary[key], key


def test_sessions_carry_month_key_and_day_key(tmp_path):
    db_path = _build_db(tmp_path)
    data = build_cli_dashboard_data(db_path, otel_log_paths=[])
    by_id = {s["id"]: s for s in data["sessions"]}

    now = datetime.now()
    current_month_ts = now.replace(day=15, hour=10, minute=0, second=0, microsecond=0)
    previous_month_ts = (now.replace(day=1) - timedelta(days=1)).replace(day=15, hour=10, minute=0, second=0, microsecond=0)
    assert by_id["current-session"]["monthKey"] == current_month_ts.strftime("%Y-%m")
    assert by_id["current-session"]["dayKey"] == current_month_ts.strftime("%Y-%m-%d")
    assert by_id["previous-session"]["monthKey"] == previous_month_ts.strftime("%Y-%m")


def test_periods_block_present_and_empty_when_db_unavailable(tmp_path):
    missing_db = str(tmp_path / "missing.db")
    data = build_cli_dashboard_data(missing_db, otel_log_paths=[])
    assert data["available"] is False
    periods = data["periods"]
    assert periods["allTime"]["summary"] == {}
    assert periods["monthly"]["summary"] == {}
    assert periods["monthly"]["monthKey"] is None
