"""Tests for claude_insights_export.py -- the /insights local-cache replay.

The fixtures write the same two JSON shapes `/insights` itself produces
(`session-meta/<id>.json`, `facets/<id>.json`) to a temp directory, so nothing here reads a
developer's own `~/.claude/usage-data/` and nothing touches the network.

Like test_chronicle_export.py, the point of several of these is a privacy contract: only the
columns this module declares may leave the process, so a field added to either cache in a future
Claude Code release does not silently start leaking into OpenObserve just because it happens to be
present in the JSON.
"""
from __future__ import annotations

import json

import pytest

import claude_insights_export as cie

META = {
    "session_id": "s1",
    "project_path": "C:\\work\\repo",
    "start_time": "2026-08-20T09:00:00.000Z",
    "duration_minutes": 42,
    "user_message_count": 5,
    "assistant_message_count": 30,
    "tool_counts": {"Bash": 10, "Read": 25, "Edit": 3},
    "languages": {"Python": 8, "Markdown": 2},
    "git_commits": 1,
    "git_pushes": 0,
    "input_tokens": 500,
    "output_tokens": 12000,
    "user_interruptions": 0,
    "tool_errors": 2,
    "lines_added": 80,
    "lines_removed": 5,
    "files_modified": 3,
    "uses_task_agent": False,
    "uses_mcp": True,
    "uses_web_search": False,
    "uses_web_fetch": False,
    "first_prompt": "the truncated first prompt, already cut by /insights itself",
    # Present in the real cache, never declared as a column this module sends. A future field
    # showing up here and nowhere in claude_insights_export.META_COLUMNS is exactly what
    # test_only_declared_columns_leave_the_process guards against.
    "user_message_timestamps": ["2026-08-20T09:01:00.000Z"],
    "message_hours": [9, 9, 10],
}

FACETS = {
    "session_id": "s1",
    "outcome": "mostly_achieved",
    "session_type": "iterative_refinement",
    "claude_helpfulness": "very_helpful",
    "primary_success": "correct_code_edits",
    "underlying_goal": "Build a thing",
    "brief_summary": "Did the thing, mostly.",
    "friction_detail": "One wrong turn before the right approach.",
    "goal_categories": {"feature_enhancement": 2, "documentation": 1},
    "friction_counts": {"wrong_approach": 1},
    "user_satisfaction_counts": {"likely_satisfied": 3, "dissatisfied": 1},
}

SECRET_TRANSCRIPT_LINE = "the full assistant reply text that must never be exported"


def write_cache(tmp_path, sessions):
    """sessions: {session_id: (meta_overrides, facets_overrides_or_None)}."""
    root = tmp_path / "usage-data"
    (root / "session-meta").mkdir(parents=True)
    (root / "facets").mkdir(parents=True)
    for session_id, (meta_overrides, facets_overrides) in sessions.items():
        meta = {**META, "session_id": session_id, **(meta_overrides or {})}
        (root / "session-meta" / f"{session_id}.json").write_text(json.dumps(meta), encoding="utf-8")
        if facets_overrides is not None:
            facets = {**FACETS, "session_id": session_id, **facets_overrides}
            (root / "facets" / f"{session_id}.json").write_text(json.dumps(facets), encoding="utf-8")
    return root


@pytest.fixture
def cache_dir(tmp_path):
    return write_cache(tmp_path, {"s1": ({}, {})})


def test_build_session_row_merges_meta_and_facets(cache_dir):
    row = cie.build_session_row(cache_dir / "session-meta" / "s1.json",
                                cache_dir / "facets" / "s1.json", "tester", 123)
    assert row["session_id"] == "s1"
    assert row["service_user"] == "tester"
    assert row["captured_at"] == 123
    assert row["duration_minutes"] == 42
    assert row["outcome"] == "mostly_achieved"
    assert row["brief_summary"] == "Did the thing, mostly."


def test_bool_columns_are_sent_as_zero_or_one_not_json_booleans(cache_dir):
    """openobserve/seed_schema.py has no boolean-column machinery -- see BOOL_AS_INT_COLUMNS."""
    row = cie.build_session_row(cache_dir / "session-meta" / "s1.json",
                                cache_dir / "facets" / "s1.json", "tester", 1)
    assert row["uses_mcp"] == 1 and row["uses_mcp"] is not True
    assert row["uses_task_agent"] == 0 and row["uses_task_agent"] is not False


def test_missing_facets_file_is_not_an_error(tmp_path):
    root = write_cache(tmp_path, {"s2": ({}, None)})
    row = cie.build_session_row(root / "session-meta" / "s2.json", root / "facets" / "s2.json",
                                "tester", 1)
    assert row is not None
    assert "outcome" not in row
    assert "brief_summary" not in row
    assert row["duration_minutes"] == 42  # session-meta columns are still there


def test_no_start_time_is_dropped_rather_than_sent_with_a_guessed_timestamp(tmp_path):
    root = write_cache(tmp_path, {"s3": ({"start_time": None}, {})})
    row = cie.build_session_row(root / "session-meta" / "s3.json", root / "facets" / "s3.json",
                                "tester", 1)
    assert row is None


def test_only_declared_columns_leave_the_process(cache_dir):
    """The privacy contract: an undeclared field in either cache must never reach the row."""
    row = cie.build_session_row(cache_dir / "session-meta" / "s1.json",
                                cache_dir / "facets" / "s1.json", "tester", 1)
    allowed = (set(cie.ROW_IDENTITY) | set(cie.META_COLUMNS) | set(cie.FACETS_COLUMNS)
              | set(cie.DERIVED_COLUMNS) | {"_timestamp"})
    assert set(row) <= allowed
    blob = json.dumps(row)
    assert "user_message_timestamps" not in blob
    assert "message_hours" not in blob


def test_derive_row_picks_the_top_key_and_splits_satisfaction():
    derived = cie.derive_row(META, FACETS)
    assert derived["total_tool_calls"] == 38  # 10 + 25 + 3
    assert derived["primary_language"] == "Python"
    assert derived["primary_goal_category"] == "feature_enhancement"
    assert derived["primary_friction"] == "wrong_approach"
    assert derived["satisfaction_positive"] == 3
    assert derived["satisfaction_negative"] == 1


def test_derive_row_tolerates_empty_maps():
    derived = cie.derive_row({"tool_counts": {}}, {})
    assert derived["total_tool_calls"] == 0
    assert "primary_language" not in derived
    assert "primary_goal_category" not in derived
    assert derived["satisfaction_positive"] == 0
    assert derived["satisfaction_negative"] == 0


def test_scan_cache_sends_new_sessions_and_records_their_mtime(cache_dir):
    rows, to_record = cie.scan_cache(cache_dir, "tester", 1, state={})
    assert [row["session_id"] for row in rows] == ["s1"]
    assert set(to_record) == {"s1"}


def test_scan_cache_skips_a_session_whose_files_have_not_changed(cache_dir):
    _, to_record = cie.scan_cache(cache_dir, "tester", 1, state={})
    rows, _ = cie.scan_cache(cache_dir, "tester", 2, state=to_record)
    assert rows == []


def test_scan_cache_resends_a_session_whose_facets_file_changed_later(cache_dir, tmp_path):
    _, to_record = cie.scan_cache(cache_dir, "tester", 1, state={})
    # /insights re-analysed the session: the facets file gets a fresh mtime.
    facets_path = cache_dir / "facets" / "s1.json"
    facets_path.write_text(facets_path.read_text(encoding="utf-8"), encoding="utf-8")
    os_stat_touch(facets_path)
    rows, _ = cie.scan_cache(cache_dir, "tester", 2, state=to_record)
    assert [row["session_id"] for row in rows] == ["s1"]


def os_stat_touch(path):
    import os
    import time
    future = time.time() + 5
    os.utime(path, (future, future))


def test_state_round_trip(tmp_path):
    path = str(tmp_path / "state.json")
    cie.save_state(path, {"s1": 111.0})
    assert cie.load_state(path) == {"s1": 111.0}
    assert cie.load_state(path, reset=True) == {}


def test_micros_reads_insights_timestamps_and_rejects_junk():
    assert cie.micros("2026-08-20T09:00:00.000Z") == 1787216400000000
    assert cie.micros("not a date") is None
    assert cie.micros(None) is None


def test_endpoint_ignores_the_single_stream_openobserve_url(monkeypatch):
    """$OPENOBSERVE_URL names the analyzer's insights stream; honouring it would misfile every row."""
    monkeypatch.setenv("OPENOBSERVE_URL", "http://host:5080/api/default/insights/_json")
    endpoint = cie.endpoint_for("http://host:5080", "default")
    assert endpoint == "http://host:5080/api/default/claude_insights_sessions/_json"


def test_endpoint_override_wins_over_base_and_org():
    endpoint = cie.endpoint_for("http://host:5080", "default", endpoint="https://proxy/x/_json")
    assert endpoint == "https://proxy/x/_json"


def test_missing_cache_directory_is_not_an_error(tmp_path):
    """Unlike chronicle_export.open_copy on a missing session-store.db: not every machine has run
    /insights, and that is a normal state rather than a misconfiguration -- see the module
    docstring's THIS DATA IS PER MACHINE section."""
    report = cie.export_claude_insights(cache_dir=str(tmp_path / "nope"), user="tester",
                                        username="u", password="p")
    assert report["ok"] is True
    assert report["sent"] == 0


def test_missing_credentials_are_reported_before_anything_is_read(cache_dir, tmp_path, monkeypatch):
    monkeypatch.delenv("OPENOBSERVE_USER", raising=False)
    monkeypatch.delenv("OPENOBSERVE_PASSWORD", raising=False)
    monkeypatch.setattr(cie, "send_events",
                        lambda *a, **k: pytest.fail("must not send without credentials"))
    report = cie.export_claude_insights(cache_dir=str(cache_dir), state_path=str(tmp_path / "s.json"),
                                        user="tester")
    assert report["ok"] is False
    assert "OPENOBSERVE_USER" in report["error"]


def test_dry_run_sends_nothing_and_writes_no_state(cache_dir, tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    monkeypatch.setattr(cie, "send_events", lambda *a, **k: pytest.fail("dry run must not send"))
    report = cie.export_claude_insights(cache_dir=str(cache_dir), state_path=str(state),
                                        user="tester", dry_run=True)
    assert report["dryRun"] is True
    assert not state.exists()


def test_watermark_advances_only_on_a_batch_with_no_failures(cache_dir, tmp_path, monkeypatch):
    def half_rejected(events, url, username, password, timeout=None, insecure_tls=False):
        return {"ok": True, "sent": len(events), "url": url, "status": 200,
                "response": json.dumps({"status": [{"successful": 0, "failed": len(events),
                                                    "error": "Too old data"}]})}

    monkeypatch.setattr(cie, "send_events", half_rejected)
    state = tmp_path / "state.json"
    report = cie.export_claude_insights(cache_dir=str(cache_dir), state_path=str(state),
                                        user="tester", username="u", password="p")
    assert report["ok"] is False
    assert report["failed"] > 0
    assert json.loads(state.read_text(encoding="utf-8")) == {}


def test_a_clean_batch_records_the_watermark_and_the_next_run_is_empty(cache_dir, tmp_path,
                                                                       monkeypatch):
    sent: list = []

    def accept(events, url, username, password, timeout=None, insecure_tls=False):
        sent.extend(events)
        return {"ok": True, "sent": len(events), "url": url, "status": 200,
                "response": json.dumps({"status": [{"successful": len(events), "failed": 0}]})}

    monkeypatch.setattr(cie, "send_events", accept)
    state = tmp_path / "state.json"
    first = cie.export_claude_insights(cache_dir=str(cache_dir), state_path=str(state),
                                       user="tester", username="u", password="p")
    assert first["ok"] is True
    assert first["sent"] == len(sent) == 1

    second = cie.export_claude_insights(cache_dir=str(cache_dir), state_path=str(state),
                                        user="tester", username="u", password="p")
    assert second["sent"] == 0

    recorded = json.loads(state.read_text(encoding="utf-8"))
    assert set(recorded) == {"s1"}


def test_default_user_prefers_claude_user(monkeypatch):
    monkeypatch.setenv("CLAUDE_USER", "someone-else")
    assert cie.default_user() == "someone-else"
