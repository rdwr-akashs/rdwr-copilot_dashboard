"""Tests for cli_usage.parse_cli_otel_files() against the fake OTel JSONL export."""
from __future__ import annotations

from cli_usage import parse_cli_otel_files


def test_otel_available_true_for_fake_export(fake_otel_jsonl):
    data = parse_cli_otel_files([fake_otel_jsonl])
    assert data["available"] is True
    assert data["paths"] == [fake_otel_jsonl]


def test_tools_aggregated_per_tool_name(fake_otel_jsonl):
    data = parse_cli_otel_files([fake_otel_jsonl])
    tools_by_name = {row["tool"]: row for row in data["tools"]}

    assert set(tools_by_name) == {"read_file", "edit_file", "bash"}

    read_file = tools_by_name["read_file"]
    assert read_file["calls"] == 2
    assert read_file["totalDurationMs"] == 250 + 150
    assert read_file["avgDurationMs"] == (250 + 150) / 2
    assert read_file["sessionCount"] == 1

    edit_file = tools_by_name["edit_file"]
    assert edit_file["calls"] == 1
    assert edit_file["totalDurationMs"] == 1000

    bash = tools_by_name["bash"]
    assert bash["calls"] == 1
    assert bash["totalDurationMs"] == 2500


def test_spans_joined_onto_correct_sessions(fake_otel_jsonl):
    data = parse_cli_otel_files([fake_otel_jsonl])
    tools_by_session = data["toolsBySession"]

    session_1_tools = {row["tool"] for row in tools_by_session["session-1"]}
    assert session_1_tools == {"read_file", "edit_file"}

    session_2_tools = {row["tool"]: row for row in tools_by_session["session-2"]}
    assert set(session_2_tools) == {"bash"}
    assert session_2_tools["bash"]["calls"] == 1


def test_missing_files_are_silently_skipped(tmp_path):
    missing = str(tmp_path / "does-not-exist.jsonl")
    data = parse_cli_otel_files([missing])
    assert data["available"] is False
    assert data["tools"] == []


def test_empty_paths_list_returns_unavailable():
    data = parse_cli_otel_files([])
    assert data["available"] is False
    assert data["tools"] == []
    assert data["toolsBySession"] == {}


def test_none_paths_returns_unavailable():
    data = parse_cli_otel_files(None)
    assert data["available"] is False
