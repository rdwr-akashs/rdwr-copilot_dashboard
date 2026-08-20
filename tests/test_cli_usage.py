"""Tests for cli_usage.build_cli_dashboard_data() against the fake CLI session-store.db."""
from __future__ import annotations

import os

from cli_usage import build_cli_dashboard_data


def test_available_true_for_fake_db(fake_cli_db):
    data = build_cli_dashboard_data(fake_cli_db, otel_log_paths=[])
    assert data["available"] is True
    assert data["dbPath"] == fake_cli_db


def test_summary_counts(fake_cli_db):
    data = build_cli_dashboard_data(fake_cli_db, otel_log_paths=[])
    summary = data["summary"]

    assert summary["sessionCount"] == 3
    assert summary["callCount"] == 5  # 5 rows inserted into assistant_usage_events
    assert summary["totalInput"] == 1000 + 1500 + 2000 + 2500 + 500
    assert summary["totalOutput"] == 200 + 300 + 400 + 500 + 100
    assert summary["totalCached"] == 100 + 800 + 500 + 2000 + 0
    assert summary["totalCost"] > 0
    assert summary["fileCount"] == 4  # 4 distinct file paths (test_cli_usage.py touched twice)


def test_by_model_breakdown_covers_both_models(fake_cli_db):
    data = build_cli_dashboard_data(fake_cli_db, otel_log_paths=[])
    model_names = {row["model"] for row in data["byModel"]}
    assert model_names == {"claude-sonnet-4.5", "gpt-5.4"}

    claude_row = next(row for row in data["byModel"] if row["model"] == "claude-sonnet-4.5")
    # session-1 (2 events) + session-3 (1 event) = 3 calls across 2 sessions.
    assert claude_row["calls"] == 3
    assert claude_row["sessionCount"] == 2

    gpt_row = next(row for row in data["byModel"] if row["model"] == "gpt-5.4")
    assert gpt_row["calls"] == 2
    assert gpt_row["sessionCount"] == 1


def test_files_list_present(fake_cli_db):
    data = build_cli_dashboard_data(fake_cli_db, otel_log_paths=[])
    paths = {row["path"] for row in data["files"]}
    assert "auth/login.py" in paths
    assert "tests/test_cli_usage.py" in paths
    # tests/test_cli_usage.py was touched twice (create + edit) in one session.
    touched_twice = next(row for row in data["files"] if row["path"] == "tests/test_cli_usage.py")
    assert touched_twice["touches"] == 2
    assert touched_twice["created"] == 1
    assert touched_twice["edited"] == 1


def test_sessions_have_turns_and_model_breakdown(fake_cli_db):
    data = build_cli_dashboard_data(fake_cli_db, otel_log_paths=[])
    session_1 = next(row for row in data["sessions"] if row["id"] == "session-1")
    assert session_1["callCount"] == 2
    assert session_1["turnCount"] == 2
    assert len(session_1["turns"]) == 2
    assert session_1["models"] == ["claude-sonnet-4.5"]


def test_nonexistent_db_path_returns_unavailable_without_raising(tmp_path):
    missing_path = str(tmp_path / "does-not-exist" / "session-store.db")
    data = build_cli_dashboard_data(missing_path, otel_log_paths=[])
    assert data["available"] is False
    assert data["sessions"] == []
    assert data["byModel"] == []
    assert data["summary"] == {}


def test_none_db_path_with_no_default_returns_unavailable(monkeypatch, tmp_path):
    # Ensure no ambient COPILOT_CLI_DB / real ~/.copilot db leaks into the test.
    monkeypatch.delenv("COPILOT_CLI_DB", raising=False)
    monkeypatch.setattr(os.path, "isfile", lambda path: False)
    data = build_cli_dashboard_data(None, otel_log_paths=[])
    assert data["available"] is False
