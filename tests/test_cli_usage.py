"""Tests for cli_usage.build_cli_dashboard_data() against the fake CLI session-store.db."""
from __future__ import annotations

import json
import os
import sqlite3

import pytest

import diagnostics
from cli_usage import (
    REASON_DB_ABSENT,
    REASON_DB_LOCKED,
    build_cli_dashboard_data,
)
from model_pricing import nano_aiu_to_usd, usd_to_nano_aiu


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


# --------------------------------------------------------------------------
# `available: False` used to conflate three very different situations: never
# used the CLI, DB locked by a running copilot process, and a query/schema
# failure. Only the last is a bug and only the middle is worth retrying, so the
# flag alone could not drive any useful advice. `reason` separates them while
# `available` keeps its historic meaning for the frontend.
# --------------------------------------------------------------------------

def test_absent_db_reports_a_benign_reason_and_no_diagnostic(tmp_path):
    diagnostics.reset()
    missing_path = str(tmp_path / "does-not-exist" / "session-store.db")
    data = build_cli_dashboard_data(missing_path, otel_log_paths=[])
    assert data["reason"] == REASON_DB_ABSENT
    # Never having used the CLI is not a failure. Reporting it would put a
    # permanent warning in front of every chat-only user.
    assert diagnostics.entries() == []
    diagnostics.reset()


def test_present_but_unopenable_db_reports_a_cost_impacting_diagnostic(tmp_path, monkeypatch):
    diagnostics.reset()
    db_path = tmp_path / "session-store.db"
    db_path.write_bytes(b"this is not a sqlite database")

    def refuse(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(sqlite3, "connect", refuse)
    data = build_cli_dashboard_data(str(db_path), otel_log_paths=[])

    assert data["available"] is False
    assert data["reason"] == REASON_DB_LOCKED
    entries = diagnostics.entries()
    assert [entry["code"] for entry in entries] == [diagnostics.CODE_CLI_DB_LOCKED]
    # The CLI half of the spend is missing entirely, which understates the total.
    assert entries[0]["impact"] == "cost"
    diagnostics.reset()


def test_healthy_db_reports_no_diagnostics(fake_cli_db):
    diagnostics.reset()
    data = build_cli_dashboard_data(fake_cli_db, otel_log_paths=[])
    assert data["available"] is True
    assert diagnostics.entries() == []
    diagnostics.reset()


def test_none_db_path_with_no_default_returns_unavailable(monkeypatch, tmp_path):
    # Ensure no ambient COPILOT_CLI_DB / real ~/.copilot db leaks into the test.
    monkeypatch.delenv("COPILOT_CLI_DB", raising=False)
    monkeypatch.setattr(os.path, "isfile", lambda path: False)
    data = build_cli_dashboard_data(None, otel_log_paths=[])
    assert data["available"] is False


# --------------------------------------------------------------------------
# Cost provenance: billed > rates > estimate
#
# `assistant_usage_events` carries what GitHub actually charged. These tests
# pin the precedence, because a silent fall back to the published-rate estimate
# is exactly the kind of regression that would leave the dashboard confidently
# reporting the wrong number.
# --------------------------------------------------------------------------

TOKEN_DETAILS_COLUMNS = (
    "session_id, turn_index, model, input_tokens, output_tokens, cache_read_tokens, "
    "cache_write_tokens, reasoning_tokens, duration_ms, created_at"
)


def _billing_db(tmp_path, events, columns=("total_nano_aiu", "request_multiplier", "token_details_json")):
    """A minimal session-store.db with a chosen subset of the billing columns.

    Older CLI builds have no billing columns at all, so `columns` lets a test
    build that shape too and assert the estimate fallback still works.
    """
    path = tmp_path / "session-store.db"
    con = sqlite3.connect(str(path))
    cur = con.cursor()
    cur.execute(
        "CREATE TABLE sessions (id TEXT, cwd TEXT, repository TEXT, branch TEXT, summary TEXT, "
        "created_at TEXT, updated_at TEXT)"
    )
    billing_ddl = "".join(f", {name} {'TEXT' if name.endswith('_json') else 'REAL'}" for name in columns)
    cur.execute(
        "CREATE TABLE assistant_usage_events (session_id TEXT, turn_index INTEGER, model TEXT, "
        "input_tokens INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER, "
        f"cache_write_tokens INTEGER, reasoning_tokens INTEGER, duration_ms INTEGER, created_at TEXT{billing_ddl})"
    )
    cur.execute("CREATE TABLE turns (session_id TEXT, turn_index INTEGER, user_message TEXT, assistant_response TEXT, timestamp TEXT)")
    cur.execute("CREATE TABLE session_files (session_id TEXT, file_path TEXT, tool_name TEXT, first_seen_at TEXT)")
    cur.execute(
        "INSERT INTO sessions VALUES ('s1', '/repo', 'org/repo', 'main', 'Billing', '2026-01-01T10:00:00Z', '2026-01-01T10:30:00Z')"
    )
    all_columns = TOKEN_DETAILS_COLUMNS + "".join(f", {name}" for name in columns)
    placeholders = ", ".join("?" * (10 + len(columns)))
    cur.executemany(f"INSERT INTO assistant_usage_events ({all_columns}) VALUES ({placeholders})", events)
    con.commit()
    con.close()
    return str(path)


def _token_details(entries):
    """Build a `token_details_json` payload: (tokenType, tokenCount, usd_per_1m)."""
    return json.dumps([
        {
            "tokenType": token_type,
            "tokenCount": count,
            "batchSize": 1_000_000,
            # costPerBatch is nano AIU per batchSize tokens; $1/1M == 1e11 nano AIU.
            "costPerBatch": usd_to_nano_aiu(usd_per_1m),
        }
        for token_type, count, usd_per_1m in entries
    ])


def test_total_nano_aiu_is_used_verbatim_as_the_cost(tmp_path):
    """GitHub's own charge wins outright - not recomputed from any rate table."""
    billed_nano_aiu = 1_234_567_890.0
    db = _billing_db(tmp_path, [
        ("s1", 0, "claude-sonnet-4.5", 1000, 200, 100, 50, 0, 900, "2026-01-01T10:00:05Z",
         billed_nano_aiu, 1.0, None),
    ])
    data = build_cli_dashboard_data(db, otel_log_paths=[])
    summary = data["summary"]

    assert summary["totalCost"] == pytest.approx(nano_aiu_to_usd(billed_nano_aiu))
    assert summary["costSource"] == "billed"
    assert summary["costExact"] is True
    assert summary["costSources"] == {"billed": 1}
    # 1 credit = $0.01.
    assert summary["totalCredits"] == pytest.approx(summary["totalCost"] / 0.01)
    # The component split is rescaled to agree with the billed total.
    assert sum(summary["costByType"].values()) == pytest.approx(summary["totalCost"])


def test_token_details_rates_are_exact_without_a_billed_total(tmp_path):
    """When `total_nano_aiu` is NULL but the per-token rates GitHub applied are
    recorded, the cost is still exact - just derived from those rates."""
    db = _billing_db(tmp_path, [
        ("s1", 0, "claude-sonnet-4.5", 1000, 200, 100, 50, 0, 900, "2026-01-01T10:00:05Z",
         None, 1.0, _token_details([
             ("input", 850, 3.00), ("cache_read", 100, 0.30),
             ("cache_write", 50, 3.75), ("output", 200, 15.00),
         ])),
    ])
    summary = build_cli_dashboard_data(db, otel_log_paths=[])["summary"]

    assert summary["costSource"] == "rates"
    assert summary["costExact"] is True
    expected = (850 * 3.00 + 100 * 0.30 + 50 * 3.75 + 200 * 15.00) / 1_000_000
    assert summary["totalCost"] == pytest.approx(expected)


def test_token_details_rates_beat_the_published_table(tmp_path):
    """A promotion, the auto-model-selection discount, or a long-context tier
    can all make the applied rate differ from list price. The recorded rate wins."""
    db = _billing_db(tmp_path, [
        ("s1", 0, "claude-sonnet-4.5", 1_000_000, 0, 0, 0, 0, 900, "2026-01-01T10:00:05Z",
         None, 1.0, _token_details([("input", 1_000_000, 0.50)])),
    ])
    summary = build_cli_dashboard_data(db, otel_log_paths=[])["summary"]
    # $0.50/1M as recorded, not claude-sonnet-4.5's $3.00/1M list price.
    assert summary["totalCost"] == pytest.approx(0.50)


def test_missing_billing_columns_fall_back_to_a_flagged_estimate(tmp_path):
    """An older DB without the billing columns must still load, and must label
    its cost as an estimate rather than passing it off as exact."""
    db = _billing_db(tmp_path, [
        ("s1", 0, "claude-sonnet-4.5", 1000, 200, 100, 50, 0, 900, "2026-01-01T10:00:05Z"),
    ], columns=())
    summary = build_cli_dashboard_data(db, otel_log_paths=[])["summary"]

    assert summary["costSource"] == "estimate"
    assert summary["costExact"] is False
    expected = (850 * 3.00 + 100 * 0.30 + 50 * 3.75 + 200 * 15.00) / 1_000_000
    assert summary["totalCost"] == pytest.approx(expected)


def test_mixed_sources_are_labelled_mixed_and_not_exact(tmp_path):
    """A bucket where some calls fell back must not be labelled exact - that
    would claim precision the number does not have."""
    db = _billing_db(tmp_path, [
        ("s1", 0, "claude-sonnet-4.5", 1000, 200, 100, 50, 0, 900, "2026-01-01T10:00:05Z",
         500_000_000.0, 1.0, None),
        ("s1", 1, "claude-sonnet-4.5", 1000, 200, 100, 50, 0, 900, "2026-01-01T10:10:05Z",
         None, 1.0, None),
    ])
    summary = build_cli_dashboard_data(db, otel_log_paths=[])["summary"]

    assert summary["costSource"] == "mixed"
    assert summary["costExact"] is False
    assert summary["costSources"] == {"billed": 1, "estimate": 1}


def test_cost_is_summed_per_call_not_repriced_from_aggregated_tokens(tmp_path):
    """Two calls billed at different effective rates must add up to the sum of
    what each was charged; re-pricing the month's tokens in one go would erase
    the difference."""
    db = _billing_db(tmp_path, [
        ("s1", 0, "claude-sonnet-4.5", 1_000_000, 0, 0, 0, 0, 900, "2026-01-01T10:00:05Z",
         None, 1.0, _token_details([("input", 1_000_000, 3.00)])),
        ("s1", 1, "claude-sonnet-4.5", 1_000_000, 0, 0, 0, 0, 900, "2026-01-01T10:10:05Z",
         None, 1.0, _token_details([("input", 1_000_000, 0.50)])),
    ])
    data = build_cli_dashboard_data(db, otel_log_paths=[])

    assert data["summary"]["totalCost"] == pytest.approx(3.50)
    assert data["periods"]["allTime"]["summary"]["totalCost"] == pytest.approx(3.50)
    assert sum(row["cost"] for row in data["sessions"]) == pytest.approx(3.50)
    assert sum(row["cost"] for row in data["byModel"]) == pytest.approx(3.50)


def test_input_tokens_are_split_into_billable_categories(tmp_path):
    """`input_tokens` is all-inclusive, so the billable (uncached) remainder is
    input - cache_read - cache_write."""
    db = _billing_db(tmp_path, [
        ("s1", 0, "claude-sonnet-4.5", 1000, 200, 100, 50, 0, 900, "2026-01-01T10:00:05Z",
         None, 1.0, None),
    ])
    summary = build_cli_dashboard_data(db, otel_log_paths=[])["summary"]

    assert summary["totalInput"] == 1000
    assert summary["totalCached"] == 100
    assert summary["totalCacheWrite"] == 50
    assert summary["totalInputBillable"] == 850
    assert summary["totalUncached"] == 850


def test_period_rollups_carry_source_counts_through(tmp_path):
    """Period bundles fold already-rendered session rows, so they read
    `costSources` rather than the raw accumulator key."""
    db = _billing_db(tmp_path, [
        ("s1", 0, "claude-sonnet-4.5", 1000, 200, 100, 50, 0, 900, "2026-01-01T10:00:05Z",
         500_000_000.0, 1.0, None),
    ])
    all_time = build_cli_dashboard_data(db, otel_log_paths=[])["periods"]["allTime"]

    assert all_time["summary"]["costSources"] == {"billed": 1}
    assert all_time["summary"]["costExact"] is True
    assert all_time["byModel"][0]["costSources"] == {"billed": 1}
    assert all_time["byModel"][0]["costExact"] is True


def test_otel_never_overrides_the_billed_cost(fake_cli_db, fake_otel_jsonl):
    """OTel is a cross-check, not a cost source: the reported cost is the DB's,
    and any disagreement surfaces as a reconciliation delta instead."""
    with_otel = build_cli_dashboard_data(fake_cli_db, otel_log_paths=[fake_otel_jsonl])
    without_otel = build_cli_dashboard_data(fake_cli_db, otel_log_paths=[])

    assert with_otel["summary"]["totalCost"] == without_otel["summary"]["totalCost"]
    # The fixture's spend metric is built to agree exactly with the DB.
    assert with_otel["otelReconciliation"]["spend"]["delta"] == pytest.approx(0.0)


def test_reconciliation_reports_a_shortfall_when_otel_is_incomplete(fake_cli_db, tmp_path):
    """A partial export (collector started mid-run) must show up as a negative
    delta, not be silently absorbed."""
    path = tmp_path / "partial.jsonl"
    path.write_text(json.dumps({
        "type": "metric",
        "name": "gen_ai.client.token.usage",
        "unit": "{token}",
        "dataPoints": [{"attributes": {"gen_ai.conversation.id": "session-1", "gen_ai.token.type": "output"}, "asInt": 100}],
    }) + "\n", encoding="utf-8")

    recon = build_cli_dashboard_data(fake_cli_db, otel_log_paths=[str(path)])["otelReconciliation"]
    assert recon["available"] is True
    assert recon["tokens"]["output"]["otel"] == 100.0
    assert recon["tokens"]["output"]["db"] == 1500.0
    assert recon["tokens"]["output"]["delta"] == -1400.0
    # No spend instrument in this export, so there is nothing to compare.
    assert recon["spend"]["otel"] is None
    assert recon["spend"]["delta"] is None


def test_reconciliation_is_unavailable_without_an_otel_export(fake_cli_db):
    recon = build_cli_dashboard_data(fake_cli_db, otel_log_paths=[])["otelReconciliation"]
    assert recon == {"available": False, "tokens": {}, "spend": {}}
