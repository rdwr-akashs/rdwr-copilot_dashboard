"""Tests for cli_usage.parse_cli_otel_files() against the fake OTel JSONL export."""
from __future__ import annotations

import json

import pytest

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


def _write_jsonl_export(tmp_path, records, name="export.jsonl"):
    path = tmp_path / name
    with open(path, "w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
    return str(path)


def test_record_counts_split_spans_metrics_and_other(fake_otel_jsonl):
    data = parse_cli_otel_files([fake_otel_jsonl])
    # 4 execute_tool spans + 1 chat span; 3 metrics; the {"type": "log"} line.
    # The malformed line is not counted at all - it never parses.
    assert data["recordCounts"] == {"span": 5, "metric": 3, "other": 1}


def test_token_metrics_and_span_attributes_sum_to_billed_totals(fake_otel_jsonl):
    """The fixture is built to agree exactly with fake_cli_db's billed tokens."""
    data = parse_cli_otel_files([fake_otel_jsonl])
    assert data["tokens"] == {
        "input": 4050.0,
        "cache_read": 3400.0,
        "cache_write": 50.0,
        "output": 1500.0,
    }


def test_token_metrics_attributed_per_session(fake_otel_jsonl):
    by_session = parse_cli_otel_files([fake_otel_jsonl])["tokensBySession"]

    # session-1 from a metric with plain-object attributes.
    assert by_session["session-1"] == {
        "input": 1550.0, "cache_read": 900.0, "cache_write": 50.0, "output": 500.0,
    }
    # session-2 from the same metric, but protobuf-shaped attribute lists.
    assert by_session["session-2"] == {
        "input": 2000.0, "cache_read": 2500.0, "cache_write": 0.0, "output": 900.0,
    }
    # session-3 from `gen_ai.usage.*` attributes on a `chat` span, not a metric.
    assert by_session["session-3"] == {
        "input": 500.0, "cache_read": 0.0, "cache_write": 0.0, "output": 100.0,
    }


def test_every_instrument_is_reported_with_unit_and_kind(fake_otel_jsonl):
    """Instrument names are undocumented and vary by CLI build, so the parser
    reports what it saw rather than silently ignoring unknown instruments."""
    instruments = {row["instrument"]: row for row in parse_cli_otel_files([fake_otel_jsonl])["instruments"]}

    assert instruments["gen_ai.client.token.usage"]["kind"] == "token"
    assert instruments["gen_ai.client.token.usage"]["points"] == 7
    assert instruments["gen_ai.client.token.usage"]["total"] == 8400.0
    assert instruments["copilot.aiu.spend"]["kind"] == "spend"
    assert instruments["copilot.aiu.spend"]["unit"] == "{credit}"
    # Reported even though its unit means it cannot be converted to money.
    assert instruments["copilot.billing.charge"]["kind"] == "spend"


def test_credit_denominated_spend_converts_to_usd(fake_otel_jsonl):
    spend = parse_cli_otel_files([fake_otel_jsonl])["spend"]
    assert spend["instrument"] == "copilot.aiu.spend"
    assert spend["unit"] == "{credit}"
    assert spend["raw"] == 3.47325
    # 1 AI credit = $0.01.
    assert spend["usd"] == pytest.approx(0.0347325)


def test_unrecognised_spend_unit_is_reported_raw_not_converted(tmp_path):
    """A wrong unit factor would be indistinguishable from a real cost, so an
    unknown unit must yield usd=None rather than a guess."""
    path = _write_jsonl_export(tmp_path, [
        {"type": "metric", "name": "copilot.billing.charge", "unit": "{widget}", "dataPoints": [{"value": 999.0}]},
    ])
    spend = parse_cli_otel_files([path])["spend"]
    assert spend["instrument"] == "copilot.billing.charge"
    assert spend["raw"] == 999.0
    assert spend["usd"] is None


@pytest.mark.parametrize(
    ("unit", "raw", "expected_usd"),
    [
        ("usd", 12.5, 12.5),
        ("{credit}", 100.0, 1.0),
        ("aiu", 250.0, 2.5),
        ("nano_aiu", 1_000_000_000.0, 0.01),
    ],
)
def test_spend_units_convert_at_published_rates(tmp_path, unit, raw, expected_usd):
    path = _write_jsonl_export(tmp_path, [
        {"type": "metric", "name": "copilot.spend", "unit": unit, "dataPoints": [{"value": raw}]},
    ], name=f"spend-{unit.strip('{}')}.jsonl")
    assert parse_cli_otel_files([path])["spend"]["usd"] == pytest.approx(expected_usd)


def test_token_metric_without_session_attribute_still_counts_in_totals(tmp_path):
    """An unlabelled point is missing *labelling*, not missing usage - dropping
    it would make the OTel-vs-DB reconciliation report phantom shortfalls."""
    path = _write_jsonl_export(tmp_path, [
        {
            "type": "metric",
            "name": "gen_ai.client.token.usage",
            "unit": "{token}",
            "dataPoints": [{"attributes": {"gen_ai.token.type": "output"}, "asInt": 42}],
        },
    ])
    data = parse_cli_otel_files([path])
    assert data["tokens"]["output"] == 42.0
    assert data["tokensBySession"] == {}


def test_token_category_falls_back_to_instrument_name_longest_marker_first(tmp_path):
    """`cache_read_input_tokens` contains "input"; the category must still be
    cache_read, so name-marker matching has to be longest-first."""
    path = _write_jsonl_export(tmp_path, [
        {
            "type": "metric",
            "name": "copilot.cache_read_input_tokens",
            "unit": "{token}",
            "dataPoints": [{"attributes": {"gen_ai.conversation.id": "s1"}, "asInt": 77}],
        },
    ])
    tokens = parse_cli_otel_files([path])["tokens"]
    assert tokens["cache_read"] == 77.0
    assert tokens["input"] == 0.0


def test_histogram_sum_is_used_as_the_quantity(tmp_path):
    path = _write_jsonl_export(tmp_path, [
        {
            "type": "metric",
            "name": "gen_ai.client.token.usage",
            "unit": "{token}",
            "histogram": {
                "dataPoints": [
                    {"attributes": {"gen_ai.token.type": "input"}, "sum": 1234, "count": 7},
                ]
            },
        },
    ])
    assert parse_cli_otel_files([path])["tokens"]["input"] == 1234.0


def test_metric_only_export_is_available(tmp_path):
    """An export with metrics but no spans still counts as available data."""
    path = _write_jsonl_export(tmp_path, [
        {"type": "metric", "name": "gen_ai.client.token.usage", "unit": "{token}",
         "dataPoints": [{"attributes": {"gen_ai.token.type": "input"}, "asInt": 5}]},
    ])
    data = parse_cli_otel_files([path])
    assert data["available"] is True
    assert data["tools"] == []
