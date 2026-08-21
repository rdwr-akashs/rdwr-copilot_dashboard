"""Tests for usage_model.py: the canonical chat/CLI usage record + aggregation layer.

Expectations here are computed by hand from the synthetic input fixtures
(simple additions of the literal numbers baked into the fixtures), not by
re-deriving them from the function under test, so an arithmetic regression
in `build_unified`/`records_from_*` will show up as a real assertion failure.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from global_calculations import month_key_from_timestamp
from premium_requests import get_multiplier
from usage_model import (
    build_unified,
    day_key_ms,
    filter_records,
    month_key_ms,
    records_from_chat_sessions,
    records_from_cli,
)

# Fixed, timezone-safe anchor points. Built via datetime(...).timestamp() (not
# a hardcoded UTC epoch) so day_key_ms/month_key_ms — which both go through
# datetime.fromtimestamp (local time) — agree with these anchors regardless
# of the host's timezone.
DAY1 = datetime(2024, 6, 15, 12, 0, 0)   # June 15th, 2024
DAY2 = datetime(2024, 6, 20, 9, 0, 0)    # June 20th, 2024 (same month as DAY1)
DAY3 = datetime(2024, 7, 1, 10, 0, 0)    # July 1st, 2024 (different month)


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _chat_sessions_fixture():
    session_a = {
        "id": "sessA",
        "source_ip": "host1",
        "repository": "repoA",
        "branch": "main",
        "timestamp": _ms(DAY1),
        "events": [
            {
                "kind": "user_message",  # non-chat event; must be ignored
                "ts": _ms(DAY1),
            },
            {
                "kind": "chat",
                "model": "gpt-5.4",
                "ts": _ms(DAY1),
                "attribution_tokens": {"input": 100.0, "cached": 20.0, "uncached": 80.0, "output": 50.0, "cost": 0.01},
                "billed_tokens": {"input": 150.0, "cached": 30.0, "uncached": 120.0, "output": 60.0, "cost": 0.02},
            },
            {
                "kind": "chat",
                "model": "claude-sonnet-4.5",
                "ts": _ms(DAY1) + 100_000,  # 100s later, same day
                "attribution_tokens": {"input": 200.0, "cached": 50.0, "uncached": 150.0, "output": 100.0, "cost": 0.03},
                "billed_tokens": {"input": 210.0, "cached": 55.0, "uncached": 155.0, "output": 105.0, "cost": 0.04},
            },
        ],
    }
    # session_b has no "events" key at all -> exercises the compacted-session
    # fallback path (one record built from aggregate totals/billed_totals).
    session_b = {
        "id": "sessB",
        "source_ip": "host2",
        "repository": "repoB",
        "branch": None,
        "timestamp": _ms(DAY2),
        "model": "claude-sonnet-4.5",
        "model_names": ["claude-sonnet-4.5"],
        "chat_count": 4,
        "totals": {"input": 500.0, "cached": 100.0, "uncached": 400.0, "output": 250.0, "cost": 0.05},
        "billed_totals": {"input": 600.0, "cached": 120.0, "uncached": 480.0, "output": 300.0, "cost": 0.06},
    }
    return [session_a, session_b]


def _cli_data_fixture():
    return {
        "available": True,
        "sessions": [
            {
                "id": "cliSess1",
                "repository": "repoC",
                "branch": "dev",
                "lastActivity": _ms(DAY3),
                # 3 user prompts across 3 model calls, so prompts and calls
                # apportion 1:1 here; see
                # test_records_from_cli_prompts_apportioned_across_models for
                # the agent-loop case where they diverge.
                "turnCount": 3,
                "modelBreakdown": [
                    {"model": "gpt-5.4", "calls": 2, "input": 300.0, "cached": 50.0, "output": 80.0, "cost": 0.02},
                    {"model": "claude-sonnet-4.5", "calls": 1, "input": 100.0, "cached": 0.0, "output": 40.0, "cost": 0.01},
                ],
            },
            {
                # No modelBreakdown entries -> must be skipped entirely (no
                # record with zeroed-out fields).
                "id": "cliSessEmpty",
                "repository": None,
                "branch": None,
                "updatedAt": _ms(DAY3),
                "modelBreakdown": [],
            },
        ],
    }


# ---------------------------------------------------------------------------
# records_from_chat_sessions
# ---------------------------------------------------------------------------

def test_records_from_chat_sessions_per_event_and_fallback():
    records = records_from_chat_sessions(_chat_sessions_fixture())
    assert len(records) == 3  # 2 chat events from session A + 1 fallback record from session B

    sess_a_records = [r for r in records if r["sessionId"] == "sessA"]
    assert len(sess_a_records) == 2
    models = sorted(r["model"] for r in sess_a_records)
    assert models == ["claude-sonnet-4.5", "gpt-5.4"]

    gpt_record = next(r for r in sess_a_records if r["model"] == "gpt-5.4")
    assert gpt_record["source"] == "chat"
    assert gpt_record["host"] == "host1"
    assert gpt_record["repository"] == "repoA"
    assert gpt_record["branch"] == "main"
    assert gpt_record["attributed"] == {"input": 100.0, "cached": 20.0, "uncached": 80.0, "output": 50.0, "cost": 0.01}
    assert gpt_record["billed"] == {"input": 150.0, "cached": 30.0, "uncached": 120.0, "output": 60.0, "cost": 0.02}
    assert gpt_record["premiumRequests"] == pytest.approx(1.0 * get_multiplier("gpt-5.4"))

    sess_b_record = next(r for r in records if r["sessionId"] == "sessB")
    assert sess_b_record["model"] == "claude-sonnet-4.5"
    assert sess_b_record["attributed"] == {"input": 500.0, "cached": 100.0, "uncached": 400.0, "output": 250.0, "cost": 0.05}
    assert sess_b_record["billed"] == {"input": 600.0, "cached": 120.0, "uncached": 480.0, "output": 300.0, "cost": 0.06}
    # Fallback scales premiumRequests by chat_count (4), not 1.
    assert sess_b_record["premiumRequests"] == pytest.approx(4.0 * get_multiplier("claude-sonnet-4.5"))


def test_records_from_chat_sessions_empty_input():
    assert records_from_chat_sessions([]) == []
    assert records_from_chat_sessions(None) == []


# ---------------------------------------------------------------------------
# records_from_cli
# ---------------------------------------------------------------------------

def test_records_from_cli_per_model_breakdown_row():
    records = records_from_cli(_cli_data_fixture())
    assert len(records) == 2  # only cliSess1's two modelBreakdown rows; cliSessEmpty is skipped

    assert all(r["sessionId"] == "cliSess1" for r in records)
    assert all(r["source"] == "cli" for r in records)
    assert all(r["host"] == "cli-local" for r in records)

    gpt_record = next(r for r in records if r["model"] == "gpt-5.4")
    assert gpt_record["repository"] == "repoC"
    assert gpt_record["branch"] == "dev"
    assert gpt_record["attributed"]["input"] == 300.0
    assert gpt_record["attributed"]["cached"] == 50.0
    assert gpt_record["attributed"]["uncached"] == 250.0  # max(0, 300-50)
    assert gpt_record["attributed"]["output"] == 80.0
    assert gpt_record["attributed"]["cost"] == 0.02
    assert gpt_record["modelCalls"] == 2.0
    assert gpt_record["promptCount"] == pytest.approx(2.0)  # 3 turns * (2 of 3 calls)
    assert gpt_record["premiumRequests"] == pytest.approx(2.0 * get_multiplier("gpt-5.4"))


def test_records_from_cli_prompts_apportioned_across_models():
    # An agent loop: 1 user prompt, 100 model calls. Premium requests are
    # charged per prompt, so the estimate must not follow the call count.
    cli_data = {
        "available": True,
        "sessions": [{
            "id": "loopSess",
            "lastActivity": _ms(DAY3),
            "turnCount": 2,
            "modelBreakdown": [
                {"model": "gpt-5.4", "calls": 75, "input": 10.0, "cached": 0.0, "output": 5.0, "cost": 0.01},
                {"model": "claude-sonnet-4.5", "calls": 25, "input": 10.0, "cached": 0.0, "output": 5.0, "cost": 0.01},
            ],
        }],
    }
    records = records_from_cli(cli_data)
    by_model = {record["model"]: record for record in records}

    assert by_model["gpt-5.4"]["modelCalls"] == 75.0
    assert by_model["claude-sonnet-4.5"]["modelCalls"] == 25.0
    # 2 prompts split 75:25 by call share -> 1.5 / 0.5, summing back to 2.
    assert by_model["gpt-5.4"]["promptCount"] == pytest.approx(1.5)
    assert by_model["claude-sonnet-4.5"]["promptCount"] == pytest.approx(0.5)
    assert sum(record["promptCount"] for record in records) == pytest.approx(2.0)
    assert by_model["gpt-5.4"]["premiumRequests"] == pytest.approx(1.5 * get_multiplier("gpt-5.4"))


def test_records_from_cli_missing_turn_count_still_counts_one_prompt():
    # A session with calls but no recorded turnCount had at least one prompt;
    # prompts must not round to zero and silently zero out premium requests.
    cli_data = {
        "available": True,
        "sessions": [{
            "id": "noTurns",
            "lastActivity": _ms(DAY3),
            "modelBreakdown": [
                {"model": "gpt-5.4", "calls": 9, "input": 10.0, "cached": 0.0, "output": 5.0, "cost": 0.01},
            ],
        }],
    }
    record = records_from_cli(cli_data)[0]
    assert record["modelCalls"] == 9.0
    assert record["promptCount"] == pytest.approx(1.0)


def test_records_from_cli_attributed_equals_billed_never_double_counts():
    # Documented no-op: CLI has no prompt-growth attribution concept, so
    # attributed/billed must be identical dicts (and thus a consumer summing
    # "both" blocks would double count -- this pins the invariant that they
    # are exactly equal so that mistake is caught immediately).
    records = records_from_cli(_cli_data_fixture())
    for record in records:
        assert record["attributed"] == record["billed"]


def test_records_from_cli_skips_sessions_with_no_model_breakdown():
    records = records_from_cli(_cli_data_fixture())
    assert all(r["sessionId"] != "cliSessEmpty" for r in records)


def test_records_from_cli_unavailable_or_empty_returns_no_records():
    assert records_from_cli({"available": False, "sessions": []}) == []
    assert records_from_cli(None) == []
    assert records_from_cli({"available": True, "sessions": []}) == []


# ---------------------------------------------------------------------------
# month_key_ms / day_key_ms format parity with global_calculations
# ---------------------------------------------------------------------------

def test_month_key_ms_matches_global_calculations_format():
    ts = _ms(DAY1)
    assert month_key_ms(ts) == month_key_from_timestamp(ts)
    assert month_key_ms(ts) == DAY1.strftime("%Y-%m")


def test_day_key_ms_format():
    ts = _ms(DAY1)
    assert day_key_ms(ts) == DAY1.strftime("%Y-%m-%d")


def test_month_key_ms_and_day_key_ms_none_for_falsy_timestamp():
    assert month_key_ms(0) is None
    assert month_key_ms(None) is None
    assert day_key_ms(0) is None
    assert day_key_ms(None) is None


# ---------------------------------------------------------------------------
# filter_records
# ---------------------------------------------------------------------------

def _sample_records_for_filtering():
    return [
        {"ts": 100, "source": "chat"},
        {"ts": 200, "source": "cli"},
        {"ts": 300, "source": "chat"},
    ]


def test_filter_records_inclusive_boundaries():
    records = _sample_records_for_filtering()
    # Both bounds equal to a record's own ts must include that record
    # (documented inclusive [start_ms, end_ms] range).
    result = filter_records(records, start_ms=200, end_ms=200)
    assert [r["ts"] for r in result] == [200]

    result = filter_records(records, start_ms=100, end_ms=300)
    assert [r["ts"] for r in result] == [100, 200, 300]

    result = filter_records(records, start_ms=101, end_ms=300)
    assert [r["ts"] for r in result] == [200, 300]

    result = filter_records(records, start_ms=100, end_ms=299)
    assert [r["ts"] for r in result] == [100, 200]


def test_filter_records_by_source():
    records = _sample_records_for_filtering()
    result = filter_records(records, source="chat")
    assert [r["ts"] for r in result] == [100, 300]


def test_filter_records_no_bounds_returns_all():
    records = _sample_records_for_filtering()
    assert filter_records(records) == records


def test_filter_records_empty_input():
    assert filter_records([]) == []
    assert filter_records(None) == []


# ---------------------------------------------------------------------------
# build_unified aggregation maths
# ---------------------------------------------------------------------------

@pytest.fixture
def unified_fixture():
    chat_records = records_from_chat_sessions(_chat_sessions_fixture())
    cli_records = records_from_cli(_cli_data_fixture())
    return build_unified(chat_records + cli_records), chat_records, cli_records


def test_build_unified_totals(unified_fixture):
    unified, chat_records, cli_records = unified_fixture
    totals = unified["totals"]

    expected_attributed_cost = 0.01 + 0.03 + 0.05 + 0.02 + 0.01  # 0.12
    expected_billed_cost = 0.02 + 0.04 + 0.06 + 0.02 + 0.01      # 0.15

    assert totals["attributed"]["cost"] == pytest.approx(expected_attributed_cost)
    assert totals["billed"]["cost"] == pytest.approx(expected_billed_cost)
    assert totals["callCount"] == 5
    assert totals["sessionCount"] == 3  # sessA, sessB, cliSess1
    expected_premium = (
        1.0 * get_multiplier("gpt-5.4")
        + 1.0 * get_multiplier("claude-sonnet-4.5")
        + 4.0 * get_multiplier("claude-sonnet-4.5")
        + 2.0 * get_multiplier("gpt-5.4")
        + 1.0 * get_multiplier("claude-sonnet-4.5")
    )
    assert totals["premiumRequests"] == pytest.approx(expected_premium)


def test_build_unified_by_model(unified_fixture):
    unified, *_ = unified_fixture
    by_model = {row["model"]: row for row in unified["byModel"]}

    assert by_model["gpt-5.4"]["callCount"] == 2
    assert by_model["gpt-5.4"]["sessionCount"] == 2  # sessA + cliSess1
    assert by_model["gpt-5.4"]["attributed"]["cost"] == pytest.approx(0.01 + 0.02)
    assert by_model["gpt-5.4"]["billed"]["cost"] == pytest.approx(0.02 + 0.02)

    assert by_model["claude-sonnet-4.5"]["callCount"] == 3
    assert by_model["claude-sonnet-4.5"]["sessionCount"] == 3  # sessA, sessB, cliSess1
    assert by_model["claude-sonnet-4.5"]["attributed"]["cost"] == pytest.approx(0.03 + 0.05 + 0.01)
    assert by_model["claude-sonnet-4.5"]["billed"]["cost"] == pytest.approx(0.04 + 0.06 + 0.01)


def test_build_unified_by_repo(unified_fixture):
    unified, *_ = unified_fixture
    by_repo = {row["repository"]: row for row in unified["byRepo"]}

    assert by_repo["repoA"]["callCount"] == 2
    assert by_repo["repoA"]["billed"]["cost"] == pytest.approx(0.02 + 0.04)
    assert by_repo["repoB"]["callCount"] == 1
    assert by_repo["repoB"]["billed"]["cost"] == pytest.approx(0.06)
    assert by_repo["repoC"]["callCount"] == 2
    assert by_repo["repoC"]["billed"]["cost"] == pytest.approx(0.02 + 0.01)


def test_build_unified_by_source(unified_fixture):
    unified, *_ = unified_fixture
    by_source = {row["source"]: row for row in unified["bySource"]}

    assert by_source["chat"]["callCount"] == 3
    assert by_source["chat"]["billed"]["cost"] == pytest.approx(0.02 + 0.04 + 0.06)
    assert by_source["cli"]["callCount"] == 2
    assert by_source["cli"]["billed"]["cost"] == pytest.approx(0.02 + 0.01)


def test_build_unified_by_host(unified_fixture):
    unified, *_ = unified_fixture
    by_host = {row["host"]: row for row in unified["byHost"]}

    assert by_host["host1"]["callCount"] == 2
    assert by_host["host2"]["callCount"] == 1
    assert by_host["cli-local"]["callCount"] == 2


def test_build_unified_daily_and_monthly_grouping(unified_fixture):
    unified, *_ = unified_fixture

    daily_by_key = {row["dayKey"]: row for row in unified["daily"]}
    assert set(daily_by_key) == {"2024-06-15", "2024-06-20", "2024-07-01"}
    assert daily_by_key["2024-06-15"]["callCount"] == 2  # both sessA chat events
    assert daily_by_key["2024-06-20"]["callCount"] == 1  # sessB fallback
    assert daily_by_key["2024-07-01"]["callCount"] == 2  # both cli modelBreakdown rows

    monthly_by_key = {row["monthKey"]: row for row in unified["monthly"]}
    assert set(monthly_by_key) == {"2024-06", "2024-07"}
    assert monthly_by_key["2024-06"]["callCount"] == 3  # sessA (2) + sessB (1)
    assert monthly_by_key["2024-06"]["billed"]["cost"] == pytest.approx(0.02 + 0.04 + 0.06)
    assert monthly_by_key["2024-07"]["callCount"] == 2
    assert monthly_by_key["2024-07"]["billed"]["cost"] == pytest.approx(0.02 + 0.01)

    # daily/monthly rows must carry a bySource breakdown.
    assert "bySource" in daily_by_key["2024-06-15"]
    assert daily_by_key["2024-06-15"]["bySource"]["chat"]["callCount"] == 2
    assert "bySource" in monthly_by_key["2024-07"]
    assert monthly_by_key["2024-07"]["bySource"]["cli"]["callCount"] == 2


def test_build_unified_range(unified_fixture):
    unified, *_ = unified_fixture
    assert unified["range"]["firstTs"] == _ms(DAY1)
    assert unified["range"]["lastTs"] == _ms(DAY3)


def test_build_unified_empty_input_yields_zeroed_aggregates_not_raises():
    unified = build_unified([])
    assert unified["daily"] == []
    assert unified["monthly"] == []
    assert unified["byModel"] == []
    assert unified["byRepo"] == []
    assert unified["bySource"] == []
    assert unified["byHost"] == []
    assert unified["totals"]["callCount"] == 0
    assert unified["totals"]["sessionCount"] == 0
    assert unified["totals"]["attributed"]["cost"] == 0.0
    assert unified["totals"]["billed"]["cost"] == 0.0
    assert unified["range"] == {"firstTs": None, "lastTs": None}

    unified_none = build_unified(None)
    assert unified_none["totals"]["callCount"] == 0


# ---------------------------------------------------------------------------
# Double-counting invariant: totals.billed.cost must equal the sum of the two
# sources' billed costs, computed independently through bySource. A future
# change that sums both attributed AND billed for one source (or otherwise
# double-counts) must fail this loudly.
# ---------------------------------------------------------------------------

def test_totals_billed_cost_equals_sum_of_chat_and_cli_source_costs(unified_fixture):
    unified, chat_records, cli_records = unified_fixture

    chat_side_cost = sum(r["billed"]["cost"] for r in chat_records)
    cli_side_cost = sum(r["billed"]["cost"] for r in cli_records)

    by_source = {row["source"]: row for row in unified["bySource"]}
    assert by_source["chat"]["billed"]["cost"] == pytest.approx(chat_side_cost)
    assert by_source["cli"]["billed"]["cost"] == pytest.approx(cli_side_cost)

    assert unified["totals"]["billed"]["cost"] == pytest.approx(chat_side_cost + cli_side_cost)
