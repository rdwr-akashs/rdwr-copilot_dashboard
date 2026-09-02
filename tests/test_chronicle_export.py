"""Tests for chronicle_export.py -- the Copilot CLI history replay.

The fixture mirrors the real `~/.copilot/session-store.db` schema (four tables,
verbatim column names) and is written to a temp path, so nothing here reads or
locks a developer's own store and nothing touches the network.

The privacy assertions are the point of this file, not a nicety: the store holds
every prompt and reply of every CLI session, and the export's contract is that
none of that text leaves the process. A regression there is invisible in a
dashboard -- it would just look like more data.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

import chronicle_export

PROMPT_TEXT = "the secret prompt nobody should ever ingest"
REPLY_TEXT = "the assistant reply, equally private, and rather longer than the prompt"
SUMMARY_TEXT = "a written summary of what this session was about"

# GitHub's own price table, as it appears in token_details_json: nano-AIU per batchSize tokens.
TOKEN_DETAILS = [
    {"tokenType": "input", "tokenCount": 1_000, "batchSize": 1_000, "costPerBatch": 3_000_000_000},
    {"tokenType": "output", "tokenCount": 500, "batchSize": 1_000, "costPerBatch": 15_000_000_000},
    {"tokenType": "cache_read", "tokenCount": 10_000, "batchSize": 1_000, "costPerBatch": 300_000_000},
    {"tokenType": "cache_write", "tokenCount": 2_000, "batchSize": 1_000, "costPerBatch": 3_750_000_000},
]


def job(stream: str) -> dict:
    return next(entry for entry in chronicle_export.JOBS if entry["stream"] == stream)


@pytest.fixture
def chronicle_db(tmp_path):
    """A two-session store: one session dated August, one dated the previous January."""
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
    # Inserted newest-first on purpose: `sessions` is watermarked on rowid, and a UUID primary
    # key that sorts *below* an earlier row is exactly what an id-ordered watermark would skip.
    connection.executemany(
        "INSERT INTO sessions (id, cwd, repository, host_type, branch, summary, created_at,"
        " updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("zzz-recent", "C:\\work\\repo", "acme/repo", "local", "main", SUMMARY_TEXT,
             "2026-08-20T09:00:00.000Z", "2026-08-20T10:00:00.000Z"),
            ("aaa-ancient", "C:\\work\\old", None, "local", None, SUMMARY_TEXT,
             "2026-01-05T09:00:00.000Z", "2026-01-05T09:30:00.000Z"),
        ],
    )
    connection.execute(
        "INSERT INTO assistant_usage_events (session_id, turn_index, agent_id, model,"
        " input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, reasoning_tokens,"
        " total_nano_aiu, request_multiplier, duration_ms, time_to_first_token_ms,"
        " inter_token_latency_ms, initiator, api_endpoint, reasoning_effort, finish_reason,"
        " content_filter_triggered, token_details_json, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("zzz-recent", 1, "agent-a", "claude-sonnet-5", 1_000, 500, 10_000, 2_000, 0,
         21_000_000_000, 1.0, 4_200, 900, 30, "user", "/chat/completions", "medium", "stop", 0,
         json.dumps(TOKEN_DETAILS), "2026-08-20T09:05:00.000Z"),
    )
    connection.execute(
        "INSERT INTO assistant_usage_events (session_id, turn_index, model, total_nano_aiu,"
        " token_details_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("aaa-ancient", 0, "gpt-5-mini", 1_000_000_000, None, "2026-01-05T09:10:00.000Z"),
    )
    connection.executemany(
        "INSERT INTO session_files (session_id, file_path, tool_name, turn_index, first_seen_at)"
        " VALUES (?, ?, ?, ?, ?)",
        [("zzz-recent", "C:\\work\\repo\\main.py", "str_replace", 1, "2026-08-20T09:06:00.000Z")],
    )
    connection.executemany(
        "INSERT INTO turns (session_id, turn_index, user_message, assistant_response, timestamp)"
        " VALUES (?, ?, ?, ?, ?)",
        [("zzz-recent", 1, PROMPT_TEXT, REPLY_TEXT, "2026-08-20T09:04:00.000Z")],
    )
    connection.commit()
    connection.close()
    return path


@pytest.fixture
def copy_dir(chronicle_db):
    target = chronicle_db.parent / "copy"
    target.mkdir()
    return str(target)


def rows_for(stream: str, chronicle_db, copy_dir, **kwargs):
    handle = chronicle_export.open_copy(chronicle_db, copy_dir)
    try:
        return chronicle_export.build_chronicle_rows(handle, job(stream), **kwargs)
    finally:
        handle.close()


def test_open_copy_leaves_the_live_store_untouched(chronicle_db, copy_dir):
    """The point of copying: the file Copilot is using is never opened for writing."""
    before = chronicle_db.stat().st_mtime_ns
    handle = chronicle_export.open_copy(chronicle_db, copy_dir)
    try:
        with pytest.raises(sqlite3.OperationalError):
            handle.execute("DELETE FROM turns")
    finally:
        handle.close()
    assert chronicle_db.stat().st_mtime_ns == before


def test_open_copy_reports_a_missing_store_rather_than_crashing(tmp_path):
    with pytest.raises(SystemExit):
        chronicle_export.open_copy(tmp_path / "nope.db", str(tmp_path))


def test_no_prompt_or_reply_text_is_ever_exported(chronicle_db, copy_dir):
    """The privacy contract, asserted over every stream rather than only over `turns`."""
    exported = []
    for entry in chronicle_export.JOBS:
        rows, _, _ = rows_for(entry["stream"], chronicle_db, copy_dir, user="tester")
        exported.append(json.dumps(rows))
    blob = "\n".join(exported)
    for secret in (PROMPT_TEXT, REPLY_TEXT, SUMMARY_TEXT):
        assert secret not in blob


def test_turns_export_lengths_only(chronicle_db, copy_dir):
    rows, _, _ = rows_for("copilot_chronicle_turns", chronicle_db, copy_dir, user="tester")
    assert len(rows) == 1
    row = rows[0]
    assert row["prompt_chars"] == len(PROMPT_TEXT)
    assert row["reply_chars"] == len(REPLY_TEXT)
    assert "user_message" not in row
    assert "assistant_response" not in row


def test_sessions_export_omits_the_summary_column(chronicle_db, copy_dir):
    rows, _, _ = rows_for("copilot_chronicle_sessions", chronicle_db, copy_dir, user="tester")
    assert rows
    assert all("summary" not in row for row in rows)
    assert {row["id"] for row in rows} == {"zzz-recent", "aaa-ancient"}


def test_sessions_watermark_is_rowid_not_the_uuid(chronicle_db, copy_dir):
    """A UUID sorts as text, so an id-ordered watermark would skip rows forever."""
    rows, highest, _ = rows_for("copilot_chronicle_sessions", chronicle_db, copy_dir,
                                user="tester")
    assert highest == 2  # insertion order, not "zzz-recent" > "aaa-ancient"
    assert all(isinstance(row["chronicle_row_id"], int) for row in rows)

    # And the incremental run after it sees nothing new, rather than re-reading the lower UUID.
    rows, _, _ = rows_for("copilot_chronicle_sessions", chronicle_db, copy_dir, since=highest,
                          user="tester")
    assert rows == []


def test_every_row_carries_identity_timestamp_and_dedupe_key(chronicle_db, copy_dir):
    for entry in chronicle_export.JOBS:
        rows, _, _ = rows_for(entry["stream"], chronicle_db, copy_dir, user="tester")
        assert rows, entry["stream"]
        for row in rows:
            assert row["service_user"] == "tester"
            assert row["_timestamp"] > 0
            assert row["chronicle_row_id"] is not None


def test_credits_come_from_the_billed_figure(chronicle_db, copy_dir):
    rows, _, _ = rows_for("copilot_chronicle_usage", chronicle_db, copy_dir, user="tester")
    billed = {row["chronicle_row_id"]: row["ai_credits"] for row in rows}
    assert billed[1] == 21.0  # 21,000,000,000 nano-AIU
    assert billed[2] == 1.0


def test_cost_split_reproduces_the_bill_and_prices_the_cache(chronicle_db, copy_dir):
    """rate x count, summed, must equal what GitHub charged -- see cost_split's docstring."""
    rows, _, _ = rows_for("copilot_chronicle_costs", chronicle_db, copy_dir, user="tester")
    priced = next(row for row in rows if row["chronicle_row_id"] == 1)
    assert priced["credits_input"] == 3.0
    assert priced["credits_output"] == 7.5
    assert priced["credits_cache_read"] == 3.0
    assert priced["credits_cache_write"] == 7.5
    assert priced["credits_total"] == 21.0
    # The invariant the credit columns rest on: recomputing from the price table reproduces the
    # figure GitHub billed. If a CLI update adds a token type this silently drops, this is where
    # it shows up rather than as a quietly low cost panel.
    usage, _, _ = rows_for("copilot_chronicle_usage", chronicle_db, copy_dir, user="tester")
    billed = next(row for row in usage if row["chronicle_row_id"] == 1)["ai_credits"]
    assert priced["credits_total"] == pytest.approx(billed, abs=0.001)
    # 12,000 cache tokens re-priced at the plain input rate, plus input and output.
    assert priced["credits_if_no_cache"] == 46.5
    assert priced["credits_cache_saved"] == 25.5

    # A row with no price table gets no credit columns rather than a guessed zero.
    unpriced = next(row for row in rows if row["chronicle_row_id"] == 2)
    assert "credits_total" not in unpriced


def test_since_is_a_floor_and_is_counted(chronicle_db, copy_dir):
    floor = chronicle_export.micros("2026-07-09")
    rows, highest, skipped = rows_for("copilot_chronicle_usage", chronicle_db, copy_dir,
                                      floor=floor, user="tester")
    assert [row["chronicle_row_id"] for row in rows] == [1]
    assert skipped == 1
    # The watermark advances only over rows actually sent, so lowering --since later picks the
    # skipped row up without needing --reset.
    assert highest == 1


def test_micros_reads_chronicle_timestamps_and_rejects_junk():
    assert chronicle_export.micros("2026-08-20T09:00:00.000Z") == 1787216400000000
    assert chronicle_export.micros("not a date") is None
    assert chronicle_export.micros(None) is None


def test_state_is_forgotten_only_for_the_named_streams(tmp_path):
    path = tmp_path / "chronicle_state.json"
    chronicle_export.save_state(str(path), {
        "copilot_chronicle_usage": {"last_id": 10},
        "copilot_chronicle_turns": {"last_id": 20},
    })
    kept = chronicle_export.load_state(str(path), reset=True, only=["copilot_chronicle_usage"])
    assert "copilot_chronicle_usage" not in kept
    assert kept["copilot_chronicle_turns"] == {"last_id": 20}


def test_dry_run_sends_nothing_and_writes_no_state(chronicle_db, tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    monkeypatch.setattr(chronicle_export, "send_events",
                        lambda *a, **k: pytest.fail("dry run must not send"))
    report = chronicle_export.export_chronicle(db_path=str(chronicle_db), state_path=str(state),
                                              user="tester", dry_run=True)
    assert report["dryRun"] is True
    assert not state.exists()


def test_watermark_advances_only_on_a_batch_with_no_failures(chronicle_db, tmp_path, monkeypatch):
    """A partial load must not mark itself complete, or the missing rows are lost silently."""
    def half_rejected(events, url, username, password, timeout=None, insecure_tls=False):
        return {"ok": True, "sent": len(events), "url": url, "status": 200,
                "response": json.dumps({"status": [{"successful": 0, "failed": len(events),
                                                    "error": "Too old data"}]})}

    monkeypatch.setattr(chronicle_export, "send_events", half_rejected)
    state = tmp_path / "state.json"
    report = chronicle_export.export_chronicle(db_path=str(chronicle_db), state_path=str(state),
                                               user="tester", username="u", password="p")
    assert report["ok"] is False
    assert report["failed"] > 0
    assert json.loads(state.read_text(encoding="utf-8")) == {}


def test_a_clean_batch_records_the_watermark_and_the_next_run_is_empty(chronicle_db, tmp_path,
                                                                      monkeypatch):
    sent: list = []

    def accept(events, url, username, password, timeout=None, insecure_tls=False):
        sent.extend(events)
        return {"ok": True, "sent": len(events), "url": url, "status": 200,
                "response": json.dumps({"status": [{"successful": len(events), "failed": 0}]})}

    monkeypatch.setattr(chronicle_export, "send_events", accept)
    state = tmp_path / "state.json"
    first = chronicle_export.export_chronicle(db_path=str(chronicle_db), state_path=str(state),
                                              user="tester", username="u", password="p")
    assert first["ok"] is True
    assert first["sent"] == len(sent) > 0

    second = chronicle_export.export_chronicle(db_path=str(chronicle_db), state_path=str(state),
                                               user="tester", username="u", password="p")
    assert second["sent"] == 0

    recorded = json.loads(state.read_text(encoding="utf-8"))
    assert set(recorded) == set(chronicle_export.stream_names())


def test_missing_credentials_are_reported_before_anything_is_read(chronicle_db, tmp_path,
                                                                 monkeypatch):
    monkeypatch.delenv("OPENOBSERVE_USER", raising=False)
    monkeypatch.delenv("OPENOBSERVE_PASSWORD", raising=False)
    monkeypatch.setattr(chronicle_export, "send_events",
                        lambda *a, **k: pytest.fail("must not send without credentials"))
    report = chronicle_export.export_chronicle(db_path=str(chronicle_db),
                                               state_path=str(tmp_path / "state.json"),
                                               user="tester")
    assert report["ok"] is False
    assert "OPENOBSERVE_USER" in report["error"]


def test_endpoint_ignores_the_single_stream_openobserve_url(monkeypatch):
    """$OPENOBSERVE_URL names the insights stream; honouring it would misfile every row."""
    monkeypatch.setenv("OPENOBSERVE_URL", "http://host:5080/api/default/insights/_json")
    monkeypatch.setenv("OPENOBSERVE_BASE_URL", "http://host:5080")
    monkeypatch.delenv("OPENOBSERVE_ORG", raising=False)
    endpoint = chronicle_export.endpoint_for("copilot_chronicle_usage")
    assert endpoint == "http://host:5080/api/default/copilot_chronicle_usage/_json"


def test_org_and_base_url_move_every_stream_together(monkeypatch):
    monkeypatch.delenv("OPENOBSERVE_BASE_URL", raising=False)
    monkeypatch.delenv("OPENOBSERVE_ORG", raising=False)
    urls = [chronicle_export.endpoint_for(stream, "https://oo.example.com/", "team")
            for stream in chronicle_export.stream_names()]
    assert all(url.startswith("https://oo.example.com/api/team/") for url in urls)
    assert all(url.endswith("/_json") for url in urls)


def test_a_per_stream_url_overrides_only_that_stream(monkeypatch):
    monkeypatch.delenv("CHRONICLE_STREAM_URLS", raising=False)
    overrides = {"copilot_chronicle_turns": "https://proxy.example/api/x/turns_v2/_json"}
    assert (chronicle_export.endpoint_for("copilot_chronicle_turns", "http://host:5080", "default",
                                         overrides)
            == "https://proxy.example/api/x/turns_v2/_json")
    assert (chronicle_export.endpoint_for("copilot_chronicle_usage", "http://host:5080", "default",
                                         overrides)
            == "http://host:5080/api/default/copilot_chronicle_usage/_json")


def test_stream_url_overrides_reads_json_text_and_ignores_junk(monkeypatch):
    """A typo in the mapping must not stop the streams that are still configured correctly."""
    monkeypatch.setenv("CHRONICLE_STREAM_URLS", '{"copilot_chronicle_files": "https://env/f/_json"}')
    assert chronicle_export.stream_url_overrides() == {"copilot_chronicle_files": "https://env/f/_json"}
    assert chronicle_export.stream_url_overrides("{not json") == {}
    assert chronicle_export.stream_url_overrides({"copilot_chronicle_files": None}) == {}


def test_export_posts_to_the_overridden_url(chronicle_db, tmp_path, monkeypatch):
    monkeypatch.delenv("CHRONICLE_STREAM_URLS", raising=False)
    targets: list[str] = []

    def accept(events, url, username, password, timeout=None, insecure_tls=False):
        targets.append(url)
        return {"ok": True, "sent": len(events), "url": url, "status": 200,
                "response": json.dumps({"status": [{"successful": len(events), "failed": 0}]})}

    monkeypatch.setattr(chronicle_export, "send_events", accept)
    report = chronicle_export.export_chronicle(
      db_path=str(chronicle_db), state_path=str(tmp_path / "state.json"), user="tester",
      username="u", password="p", base_url="http://host:5080", org="team",
      streams=["copilot_chronicle_sessions"],
      stream_urls='{"copilot_chronicle_sessions": "https://proxy.example/s/_json"}',
    )
    assert targets == ["https://proxy.example/s/_json"]
    assert report["streams"]["copilot_chronicle_sessions"]["endpoint"] == "https://proxy.example/s/_json"


def test_default_user_prefers_copilot_user(monkeypatch):
    monkeypatch.setenv("COPILOT_USER", "someone-else")
    assert chronicle_export.default_user() == "someone-else"


def test_advice_columns_cover_every_field_chronicle_advice_writes():
    """seed_schema registers these; a column it misses is a red panel, not a missing number."""
    import chronicle_advice  # imported here so a missing Copilot CLI cannot fail collection

    assert chronicle_advice.STREAM == chronicle_export.ADVICE_STREAM
    written = {"service_user", "chronicle_command", "chronicle_request", "advice_text",
               "advice_summary", "exit_code", "duration_ms", "summary_ms", "captured_at"}
    assert written == set(chronicle_export.ADVICE_COLUMNS)
