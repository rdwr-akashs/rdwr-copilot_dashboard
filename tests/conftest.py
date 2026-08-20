"""Shared pytest fixtures for the Copilot Token Dashboard test suite.

These fixtures build small, synthetic, hermetic inputs that mirror the real
on-disk/on-DB shapes the production code expects, without ever touching a
developer's real `~/.copilot/session-store.db`, real VS Code debug logs, or
the network.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

# Production modules live at the repo root (not inside a package), so make
# sure it is importable regardless of pytest's rootdir/invocation directory.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture
def tmp_cache_dir(tmp_path, monkeypatch):
    """An isolated dashboard cache root.

    Ensures tests never read/write the real shared cache locations
    (`~/.copilot-dashboard/cache` or `/mnt/radware/...`).
    """
    cache_dir = tmp_path / "dashboard-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("COPILOT_DASHBOARD_CACHE_DIR", str(cache_dir))
    # Pin the cache "shard" (normally derived from hostname/IP) so session
    # identities are deterministic across machines/CI runners.
    monkeypatch.setenv("COPILOT_DASHBOARD_CACHE_SHARD", "test-shard")
    return str(cache_dir)


@pytest.fixture
def fake_cli_db(tmp_path):
    """Build a small SQLite `session-store.db` with the schema `cli_usage.py` queries.

    Schema derived directly from the SQL in `cli_usage.py`:
      - sessions(id, cwd, repository, branch, summary, created_at, updated_at)
      - assistant_usage_events(session_id, turn_index, model, input_tokens,
        output_tokens, cache_read_tokens, cache_write_tokens, reasoning_tokens,
        duration_ms, created_at)
      - turns(session_id, turn_index, user_message, assistant_response, timestamp)
      - session_files(session_id, file_path, tool_name, first_seen_at)

    Populates 3 sessions, assistant_usage_events across 2 models, several
    turns, and several session_files rows.
    """
    db_path = tmp_path / "session-store.db"
    con = sqlite3.connect(str(db_path))
    try:
        cur = con.cursor()
        cur.execute(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                cwd TEXT,
                repository TEXT,
                branch TEXT,
                summary TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE assistant_usage_events (
                session_id TEXT,
                turn_index INTEGER,
                model TEXT,
                input_tokens INTEGER,
                output_tokens INTEGER,
                cache_read_tokens INTEGER,
                cache_write_tokens INTEGER,
                reasoning_tokens INTEGER,
                duration_ms INTEGER,
                created_at TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE turns (
                session_id TEXT,
                turn_index INTEGER,
                user_message TEXT,
                assistant_response TEXT,
                timestamp TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE session_files (
                session_id TEXT,
                file_path TEXT,
                tool_name TEXT,
                first_seen_at TEXT
            )
            """
        )

        sessions = [
            ("session-1", "/repo/a", "org/repo-a", "main", "Fix the login bug", "2026-01-01T10:00:00Z", "2026-01-01T10:30:00Z"),
            ("session-2", "/repo/b", "org/repo-b", "feature/x", "Add dashboard tests", "2026-01-02T09:00:00Z", "2026-01-02T09:45:00Z"),
            ("session-3", "/repo/a", "org/repo-a", "main", "Refactor pricing module", "2026-01-03T14:00:00Z", "2026-01-03T14:20:00Z"),
        ]
        cur.executemany(
            "INSERT INTO sessions (id, cwd, repository, branch, summary, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            sessions,
        )

        events = [
            # session_id, turn_index, model, input, output, cache_read, cache_write, reasoning, duration_ms, created_at
            ("session-1", 0, "claude-sonnet-4.5", 1000, 200, 100, 50, 0, 1200, "2026-01-01T10:00:05Z"),
            ("session-1", 1, "claude-sonnet-4.5", 1500, 300, 800, 0, 0, 1500, "2026-01-01T10:15:00Z"),
            ("session-2", 0, "gpt-5.4", 2000, 400, 500, 0, 0, 2000, "2026-01-02T09:05:00Z"),
            ("session-2", 1, "gpt-5.4", 2500, 500, 2000, 0, 0, 1800, "2026-01-02T09:30:00Z"),
            ("session-3", 0, "claude-sonnet-4.5", 500, 100, 0, 0, 0, 900, "2026-01-03T14:05:00Z"),
        ]
        cur.executemany(
            "INSERT INTO assistant_usage_events (session_id, turn_index, model, input_tokens, output_tokens, "
            "cache_read_tokens, cache_write_tokens, reasoning_tokens, duration_ms, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            events,
        )

        turns = [
            ("session-1", 0, "Fix the login bug please", "Sure, let's look at the auth module.", "2026-01-01T10:00:00Z"),
            ("session-1", 1, "Also add a test", "Added a regression test.", "2026-01-01T10:15:00Z"),
            ("session-2", 0, "Write tests for the dashboard", "Created tests/test_cli_usage.py", "2026-01-02T09:00:00Z"),
            ("session-2", 1, "Run them", "All tests pass.", "2026-01-02T09:30:00Z"),
            ("session-3", 0, "Refactor pricing", "Split calculate_cost into helpers.", "2026-01-03T14:00:00Z"),
        ]
        cur.executemany(
            "INSERT INTO turns (session_id, turn_index, user_message, assistant_response, timestamp) VALUES (?, ?, ?, ?, ?)",
            turns,
        )

        session_files = [
            ("session-1", "auth/login.py", "edit", "2026-01-01T10:00:10Z"),
            ("session-1", "tests/test_login.py", "create", "2026-01-01T10:16:00Z"),
            ("session-2", "tests/test_cli_usage.py", "create", "2026-01-02T09:06:00Z"),
            ("session-2", "tests/test_cli_usage.py", "edit", "2026-01-02T09:31:00Z"),
            ("session-3", "model_pricing.py", "edit", "2026-01-03T14:06:00Z"),
        ]
        cur.executemany(
            "INSERT INTO session_files (session_id, file_path, tool_name, first_seen_at) VALUES (?, ?, ?, ?)",
            session_files,
        )

        con.commit()
    finally:
        con.close()

    return str(db_path)


@pytest.fixture
def fake_otel_jsonl(tmp_path):
    """Build a JSONL OTel file-exporter export with `execute_tool` spans.

    Shape derived from `parse_cli_otel_files()`: each line is a JSON object
    with `type: "span"`, a `name` starting with `execute_tool`, `attributes`
    containing `gen_ai.tool.name` and `gen_ai.conversation.id` (joined onto
    `session-1` / `session-2` from `fake_cli_db`), and `startTime`/`endTime`
    as [seconds, nanoseconds] pairs.
    """
    otel_path = tmp_path / "otel-export.jsonl"
    spans = [
        {
            "type": "span",
            "name": "execute_tool read_file",
            "attributes": {"gen_ai.tool.name": "read_file", "gen_ai.conversation.id": "session-1"},
            "startTime": [1735725600, 0],
            "endTime": [1735725600, 250_000_000],
        },
        {
            "type": "span",
            "name": "execute_tool read_file",
            "attributes": {"gen_ai.tool.name": "read_file", "gen_ai.conversation.id": "session-1"},
            "startTime": [1735725610, 0],
            "endTime": [1735725610, 150_000_000],
        },
        {
            "type": "span",
            "name": "execute_tool edit_file",
            "attributes": {"gen_ai.tool.name": "edit_file", "gen_ai.conversation.id": "session-1"},
            "startTime": [1735725620, 0],
            "endTime": [1735725621, 0],
        },
        {
            "type": "span",
            "name": "execute_tool bash",
            "attributes": {"gen_ai.tool.name": "bash", "gen_ai.conversation.id": "session-2"},
            "startTime": [1735729200, 0],
            "endTime": [1735729202, 500_000_000],
        },
        # Non-span / non execute_tool lines and a malformed line should be
        # silently skipped by parse_cli_otel_files().
        {"type": "log", "name": "something-else"},
        "not even json {{{",
    ]
    with open(otel_path, "w", encoding="utf-8") as handle:
        for span in spans:
            if isinstance(span, str):
                handle.write(span + "\n")
            else:
                handle.write(json.dumps(span) + "\n")
    return str(otel_path)


@pytest.fixture
def minimal_app_data():
    """A tiny, well-shaped `app_data` dict for tests that only need
    `generate_html()` to run end-to-end (e.g. web-assembly contract checks)
    without driving the full log-parsing pipeline.
    """
    return {
        "generatedAt": "2026-01-01 00:00:00",
        "summary": {"totalCost": 1.23},
        "sessions": [],
        "analysis": {},
        "periods": {"default": "monthly", "labels": {}, "allTime": {}, "monthly": {}},
        "cli": {
            "available": False,
            "sessions": [],
            "byModel": [],
            "files": [],
            "tools": [],
            "otelAvailable": False,
            "otelPaths": [],
            "summary": {},
        },
    }


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry) + "\n")


@pytest.fixture
def fake_debug_logs(tmp_path):
    """Build a directory tree mimicking a VS Code Copilot Chat debug-log root.

    Shape derived from `per_chat_calculations.parse_session()` /
    `iter_log_streams()` / `load_model_limits()` / `parse_title()`:
      - `<log_dir>/<session_id>/main.jsonl` with `user_message`, `llm_request`,
        and `agent_response` entries (the minimal set that produces a
        session with `chat_count > 0`, which is required for the session to
        be kept).
      - Each JSONL line: {"type", "ts", "dur", "attrs": {...}}.
      - `llm_request.attrs` carries `model`, `inputTokens`, `outputTokens`,
        `cachedTokens`, `inputMessages` (empty list is valid/parsed fine).

    Two sessions are created across two models so downstream aggregation
    (byModel/analysis/monthly trends) has more than one bucket to work with.
    """
    log_dir = tmp_path / "debug-logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    base_ts = 1735725600000  # 2025-01-01T10:00:00Z in epoch ms

    session_1_dir = log_dir / "session-aaa111"
    session_1_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(
        session_1_dir / "main.jsonl",
        [
            {"type": "user_message", "ts": base_ts, "dur": 0, "attrs": {"content": "Fix the login bug"}},
            {
                "type": "llm_request",
                "ts": base_ts + 500,
                "dur": 1200,
                "attrs": {
                    "model": "claude-sonnet-4.5",
                    "inputTokens": 1000,
                    "outputTokens": 200,
                    "cachedTokens": 100,
                    "inputMessages": [],
                },
            },
            {
                "type": "agent_response",
                "ts": base_ts + 1700,
                "dur": 0,
                "attrs": {"response": [{"role": "assistant", "parts": [{"type": "text", "text": "Fixed the auth check."}]}]},
            },
        ],
    )

    session_2_dir = log_dir / "session-bbb222"
    session_2_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(
        session_2_dir / "main.jsonl",
        [
            {"type": "user_message", "ts": base_ts + 86_400_000, "dur": 0, "attrs": {"content": "Write CLI dashboard tests"}},
            {
                "type": "llm_request",
                "ts": base_ts + 86_400_500,
                "dur": 2000,
                "attrs": {
                    "model": "gpt-5.4",
                    "inputTokens": 2000,
                    "outputTokens": 400,
                    "cachedTokens": 500,
                    "inputMessages": [],
                },
            },
            {
                "type": "agent_response",
                "ts": base_ts + 86_402_500,
                "dur": 0,
                "attrs": {"response": [{"role": "assistant", "parts": [{"type": "text", "text": "Added the CLI usage tests."}]}]},
            },
        ],
    )

    return str(log_dir)
