"""Tests for chronicle_view.py -- what the Chronicle tab is told.

The fixture mirrors the real `~/.copilot/session-store.db` schema and lives in a
temp path, so nothing here reads a developer's own store and nothing touches the
network (the payload is built entirely from local state by design).

Two behaviours carry the weight here:

  * the pending count must be counted against each stream's watermark rather
    than derived as `max(id) - last_id`, because a pruned store has gaps and
    would otherwise report a backlog that does not exist;
  * the cross-foot must only compare calls that appear on both sides. A call
    with no rate table is billed but cannot be split, and if its charge landed
    on the billed side alone the panel would cry "drift" over what is really
    just missing coverage -- which would train the reader to ignore the one
    alarm that matters.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

import chronicle_view

# GitHub's own price table, as it appears in token_details_json: nano-AIU per batchSize tokens.
# 1 credit = 1e9 nano-AIU, so this call bills 3 + 7.5 + 3 + 7.5 = 21 credits.
TOKEN_DETAILS = [
    {"tokenType": "input", "tokenCount": 1_000, "batchSize": 1_000, "costPerBatch": 3_000_000_000},
    {"tokenType": "output", "tokenCount": 500, "batchSize": 1_000, "costPerBatch": 15_000_000_000},
    {"tokenType": "cache_read", "tokenCount": 10_000, "batchSize": 1_000, "costPerBatch": 300_000_000},
    {"tokenType": "cache_write", "tokenCount": 2_000, "batchSize": 1_000, "costPerBatch": 3_750_000_000},
]
PRICED_CREDITS = 21.0
UNPRICED_CREDITS = 1.0


@pytest.fixture
def store(tmp_path):
    """One priced call and one unpriced call, in two sessions."""
    path = tmp_path / "session-store.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY, cwd TEXT, repository TEXT, host_type TEXT, branch TEXT,
            summary TEXT, created_at TEXT, updated_at TEXT);
        CREATE TABLE assistant_usage_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, turn_index INTEGER,
            agent_id TEXT, parent_tool_call_id TEXT, model TEXT, input_tokens INTEGER,
            output_tokens INTEGER, cache_read_tokens INTEGER, cache_write_tokens INTEGER,
            reasoning_tokens INTEGER, total_nano_aiu INTEGER, request_multiplier REAL,
            duration_ms INTEGER, time_to_first_token_ms INTEGER, inter_token_latency_ms INTEGER,
            initiator TEXT, api_endpoint TEXT, reasoning_effort TEXT, finish_reason TEXT,
            content_filter_triggered INTEGER, token_details_json TEXT, created_at TEXT);
        CREATE TABLE session_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, file_path TEXT,
            tool_name TEXT, turn_index INTEGER, first_seen_at TEXT);
        CREATE TABLE turns (
            id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, turn_index INTEGER,
            user_message TEXT, assistant_response TEXT, timestamp TEXT);
        """
    )
    connection.executemany(
        "INSERT INTO sessions (id, cwd, repository, host_type, branch, summary, created_at,"
        " updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("sess-priced", "C:\\work\\repo", "acme/repo", "local", "main", "summary",
             "2026-08-20T09:00:00.000Z", "2026-08-20T10:00:00.000Z"),
            ("sess-unpriced", "C:\\work\\old", None, "local", None, "summary",
             "2026-01-05T09:00:00.000Z", "2026-01-05T09:30:00.000Z"),
        ],
    )
    connection.execute(
        "INSERT INTO assistant_usage_events (session_id, turn_index, model, input_tokens,"
        " output_tokens, cache_read_tokens, cache_write_tokens, total_nano_aiu,"
        " token_details_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("sess-priced", 1, "claude-sonnet-5", 1_000, 500, 10_000, 2_000,
         int(PRICED_CREDITS * 1_000_000_000), json.dumps(TOKEN_DETAILS),
         "2026-08-20T09:05:00.000Z"),
    )
    connection.execute(
        "INSERT INTO assistant_usage_events (session_id, turn_index, model, total_nano_aiu,"
        " token_details_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("sess-unpriced", 0, "gpt-5-mini", int(UNPRICED_CREDITS * 1_000_000_000), None,
         "2026-01-05T09:10:00.000Z"),
    )
    connection.executemany(
        "INSERT INTO session_files (session_id, file_path, tool_name, turn_index, first_seen_at)"
        " VALUES (?, ?, ?, ?, ?)",
        [("sess-priced", "C:\\work\\repo\\main.py", "str_replace", 1, "2026-08-20T09:06:00.000Z")],
    )
    connection.executemany(
        "INSERT INTO turns (session_id, turn_index, user_message, assistant_response, timestamp)"
        " VALUES (?, ?, ?, ?, ?)",
        [("sess-priced", 1, "prompt", "reply", "2026-08-20T09:04:00.000Z")],
    )
    connection.commit()
    connection.close()
    return path


def write_state(tmp_path, mapping):
    path = tmp_path / "chronicle_state.json"
    path.write_text(json.dumps(mapping), encoding="utf-8")
    return str(path)


def stream(payload, name):
    return next(row for row in payload["streams"] if row["stream"] == name)


def test_a_missing_store_degrades_instead_of_raising(tmp_path):
    payload = chronicle_view.build_chronicle_payload(
        db_path=str(tmp_path / "nope.db"), state_path=str(tmp_path / "state.json")
    )
    assert payload["available"] is False
    assert payload["reason"] == chronicle_view.REASON_NO_DB
    assert payload["streams"] == []
    # The state path is still reported: "where would the watermarks be?" is the
    # first thing to check when the tab says there is nothing to show.
    assert payload["statePath"] == str(tmp_path / "state.json")


def test_never_exported_means_every_row_is_pending(store, tmp_path):
    payload = chronicle_view.build_chronicle_payload(
        db_path=str(store), state_path=write_state(tmp_path, {})
    )
    usage = stream(payload, "copilot_chronicle_usage")
    assert usage["everShipped"] is False
    assert usage["rowsInDb"] == 2
    assert usage["pending"] == 2
    assert usage["shipped"] == 0
    assert payload["totals"]["lastRunAt"] is None


def test_pending_is_counted_against_the_watermark_not_the_max_id(store, tmp_path):
    # Delete the older row, leaving a gap: `max(id) - last_id` would say one row
    # is pending when the store is in fact caught up.
    connection = sqlite3.connect(store)
    connection.execute("DELETE FROM assistant_usage_events WHERE id = 1")
    connection.commit()
    connection.close()

    payload = chronicle_view.build_chronicle_payload(
        db_path=str(store),
        state_path=write_state(tmp_path, {
            "copilot_chronicle_usage": {"last_id": 2, "at": "2026-08-21T00:00:00"},
        }),
    )
    usage = stream(payload, "copilot_chronicle_usage")
    assert usage["rowsInDb"] == 1
    assert usage["pending"] == 0
    assert usage["shipped"] == 1
    assert usage["lastId"] == 2


def test_last_run_is_the_most_recent_stream_watermark(store, tmp_path):
    payload = chronicle_view.build_chronicle_payload(
        db_path=str(store),
        state_path=write_state(tmp_path, {
            "copilot_chronicle_usage": {"last_id": 2, "at": "2026-08-20T10:00:00"},
            "copilot_chronicle_costs": {"last_id": 2, "at": "2026-08-21T11:00:00"},
        }),
    )
    assert payload["totals"]["lastRunAt"] == "2026-08-21T11:00:00"


def test_the_split_reproduces_the_bill_for_every_priced_call(store, tmp_path):
    payload = chronicle_view.build_chronicle_payload(
        db_path=str(store), state_path=write_state(tmp_path, {})
    )
    drift = payload["drift"]
    assert drift["callsPriced"] == 1
    assert drift["creditsTotal"] == pytest.approx(PRICED_CREDITS)
    assert drift["aiCredits"] == pytest.approx(PRICED_CREDITS)
    assert drift["withinTolerance"] is True
    assert abs(drift["difference"]) <= chronicle_view.DRIFT_TOLERANCE_CREDITS


def test_a_call_with_no_rate_table_is_reported_as_coverage_not_as_drift(store, tmp_path):
    payload = chronicle_view.build_chronicle_payload(
        db_path=str(store), state_path=write_state(tmp_path, {})
    )
    drift = payload["drift"]
    # The unpriced call is on neither side of the cross-foot...
    assert drift["callsUnpriced"] == 1
    assert drift["creditsUnpriced"] == pytest.approx(UNPRICED_CREDITS)
    assert drift["withinTolerance"] is True
    # ...but its charge is not swept away either: the billed total includes it.
    assert drift["billedTotal"] == pytest.approx(PRICED_CREDITS + UNPRICED_CREDITS)


def test_a_dropped_token_type_shows_up_as_drift(store, tmp_path):
    # The failure this cross-foot exists to catch: the rate table prices a token
    # type the split does not sum, so the re-priced total understates the bill.
    connection = sqlite3.connect(store)
    connection.execute(
        "UPDATE assistant_usage_events SET total_nano_aiu = ? WHERE token_details_json IS NOT NULL",
        (int((PRICED_CREDITS + 5.0) * 1_000_000_000),),
    )
    connection.commit()
    connection.close()

    drift = chronicle_view.build_chronicle_payload(
        db_path=str(store), state_path=write_state(tmp_path, {})
    )["drift"]
    assert drift["withinTolerance"] is False
    assert drift["difference"] == pytest.approx(-5.0)


def test_the_cache_saving_is_the_uncached_price_minus_what_was_charged(store, tmp_path):
    totals = chronicle_view.build_chronicle_payload(
        db_path=str(store), state_path=write_state(tmp_path, {})
    )["costs"]["totals"]
    assert totals["creditsTotal"] == pytest.approx(PRICED_CREDITS)
    assert totals["creditsIfNoCache"] > totals["creditsTotal"]
    assert totals["creditsCacheSaved"] == pytest.approx(
        totals["creditsIfNoCache"] - totals["creditsTotal"], abs=1e-6
    )
    assert 0 < totals["cacheSavedPercent"] < 100


def test_buckets_are_keyed_by_model_and_by_local_day(store, tmp_path):
    costs = chronicle_view.build_chronicle_payload(
        db_path=str(store), state_path=write_state(tmp_path, {})
    )["costs"]
    # Both calls are bucketed; only the priced one contributes credits, so the
    # unpriced model must not read as a model that cost nothing to run.
    assert {row["model"] for row in costs["byModel"]} == {"claude-sonnet-5", "gpt-5-mini"}
    sonnet = next(row for row in costs["byModel"] if row["model"] == "claude-sonnet-5")
    assert sonnet["callsPriced"] == 1
    mini = next(row for row in costs["byModel"] if row["model"] == "gpt-5-mini")
    assert mini["callsPriced"] == 0
    assert mini["calls"] == 1
    # Days are sorted ascending and are calendar days, not timestamps.
    days = [row["day"] for row in costs["byDay"]]
    assert days == sorted(days)
    assert all(len(day) == 10 for day in days)


def test_endpoints_follow_the_configured_base_url_and_org(store, tmp_path):
    payload = chronicle_view.build_chronicle_payload(
        db_path=str(store),
        state_path=write_state(tmp_path, {}),
        base_url="https://observe.example.com",
        org="acme",
    )
    usage = stream(payload, "copilot_chronicle_usage")
    assert usage["endpoint"] == "https://observe.example.com/api/acme/copilot_chronicle_usage/_json"
    assert payload["advice"]["endpoint"].endswith(f"/{payload['advice']['stream']}/_json")


def test_reading_the_store_never_writes_to_it(store, tmp_path):
    before = store.stat().st_mtime_ns
    chronicle_view.build_chronicle_payload(db_path=str(store), state_path=write_state(tmp_path, {}))
    assert store.stat().st_mtime_ns == before
