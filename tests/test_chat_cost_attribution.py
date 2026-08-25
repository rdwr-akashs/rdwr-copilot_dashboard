"""Tests for how a chat turn's cost is attributed, end to end from a debug log.

`per_chat_calculations.parse_session` prices every call twice: `billed_tokens`
charges the whole cumulative prompt (what GitHub billed for that call) and
`attribution_tokens` charges only the tokens the turn newly added, so that a
session's own totals do not count a growing prompt once per turn. The two must
describe the *same* spend under two different partitions - anything that makes
attribution cheaper per token than billing turns the reallocation into a
discount, and every session/model/analysis figure in the dashboard reads the
attributed numbers.

These go through `compact_cache.parse_session_payload`, the same entry point the
cache uses, rather than reaching into the parser, so the assertions hold for the
payload the dashboard actually renders.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from compact_cache import parse_session_payload

BASE_TS = 1735725600000  # 2025-01-01T10:00:00Z in epoch ms

# gpt-5.4, above the 272K long-context threshold.
LONG_INPUT_RATE = 5.00
LONG_OUTPUT_RATE = 22.50
DEFAULT_INPUT_RATE = 2.50
DEFAULT_OUTPUT_RATE = 15.00


def _write_session(tmp_path: Path, session_id: str, calls: list[tuple[int, int, int]]) -> str:
    """Write a one-model session log with one `llm_request` per (prompt, out, cached)."""
    session_dir = tmp_path / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = [
        {"type": "user_message", "ts": BASE_TS, "dur": 0, "attrs": {"content": "Refactor the parser"}},
    ]
    for index, (prompt, output, cached) in enumerate(calls):
        rows.append({
            "type": "llm_request",
            "ts": BASE_TS + 500 + index * 1500,
            "dur": 1000,
            "attrs": {
                "model": "gpt-5.4",
                "inputTokens": prompt,
                "outputTokens": output,
                "cachedTokens": cached,
                "inputMessages": [],
            },
        })
    rows.append({
        "type": "agent_response",
        "ts": BASE_TS + 500 + len(calls) * 1500,
        "dur": 0,
        "attrs": {"response": [{"role": "assistant", "parts": [{"type": "text", "text": "Done."}]}]},
    })

    with open(session_dir / "main.jsonl", "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    return str(session_dir)


def _chat_events(session_dir: str) -> list[dict]:
    payload = parse_session_payload(session_dir)
    assert payload is not None
    return [event for event in payload["session"]["events"] if event.get("kind") == "chat"]


def test_attributed_growth_keeps_the_long_context_tier_of_the_whole_call(tmp_path):
    """The tier belongs to the call, not to the slice being attributed.

    GitHub prices every token of an over-threshold prompt at the long-context
    rates, the newly added ones included. Selecting the tier from the growth
    delta instead priced a 10K-token delta as if the call had been a 10K-token
    call, understating this turn by the full tier delta (~1.95x here) - and the
    bigger the context, the larger the share of the session it lost.
    """
    events = _chat_events(_write_session(tmp_path, "session-long", [
        (300_000, 100, 0),   # first call: segment start, billed in full
        (310_000, 200, 0),   # +10K prompt growth on a long-context call
    ]))
    assert len(events) == 2
    growth = events[1]

    assert growth["billed_tokens"]["tier"] == "long"
    assert growth["attribution_tokens"]["tier"] == "long"
    assert growth["attribution_tokens"]["input"] == 10_000
    assert growth["attribution_tokens"]["cost"] == pytest.approx(
        10_000 / 1_000_000 * LONG_INPUT_RATE + 200 / 1_000_000 * LONG_OUTPUT_RATE
    )
    # What the default tier would have charged for the same delta - the size of
    # the bug this pins.
    understated = 10_000 / 1_000_000 * DEFAULT_INPUT_RATE + 200 / 1_000_000 * DEFAULT_OUTPUT_RATE
    assert growth["attribution_tokens"]["cost"] > understated


def test_attributed_cost_never_exceeds_the_billed_cost_of_the_same_call(tmp_path):
    """Attribution reallocates a call's charge; it can only ever be a part of it."""
    for event in _chat_events(_write_session(tmp_path, "session-ratio", [
        (300_000, 100, 0),
        (310_000, 200, 50_000),
        (280_000, 150, 100_000),  # prompt shrank: a trimmed context, no negative cost
    ])):
        assert event["attribution_tokens"]["cost"] <= event["billed_tokens"]["cost"] + 1e-12
        assert event["attribution_tokens"]["cost"] >= 0.0


def test_short_prompt_calls_stay_on_the_default_tier(tmp_path):
    """The seam must not promote ordinary calls to long-context rates."""
    events = _chat_events(_write_session(tmp_path, "session-short", [
        (1_000, 100, 0),
        (5_000, 200, 0),
    ]))
    for event in events:
        assert event["billed_tokens"]["tier"] == "default"
        assert event["attribution_tokens"]["tier"] == "default"
    assert events[1]["attribution_tokens"]["cost"] == pytest.approx(
        4_000 / 1_000_000 * DEFAULT_INPUT_RATE + 200 / 1_000_000 * DEFAULT_OUTPUT_RATE
    )
