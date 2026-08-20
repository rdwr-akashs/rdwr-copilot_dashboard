"""Tests for model_pricing.py: get_pricing() lookup and calculate_cost() maths."""
from __future__ import annotations

from model_pricing import PRICING, calculate_cost, get_pricing


def test_get_pricing_exact_match():
    pricing = get_pricing("gpt-5.4")
    assert pricing == PRICING["gpt-5.4"]


def test_get_pricing_case_insensitive_exact_match():
    pricing = get_pricing("GPT-5.4")
    assert pricing == PRICING["gpt-5.4"]


def test_get_pricing_prefix_match():
    # "claude-sonnet-4.5-something" isn't an exact key but starts with a known key.
    pricing = get_pricing("claude-sonnet-4.5-preview")
    assert pricing == PRICING["claude-sonnet-4.5"]


def test_get_pricing_substring_match():
    # A vendor-qualified model name containing a known key as a substring.
    pricing = get_pricing("copilot/gpt-4o")
    assert pricing == PRICING["gpt-4o"]


def test_get_pricing_unknown_model_fallback():
    pricing = get_pricing("some-totally-unknown-model-xyz")
    assert pricing == {"input": 3.00, "cached": 0.30, "output": 15.00}


def test_get_pricing_none_model_fallback():
    pricing = get_pricing(None)
    assert pricing == {"input": 3.00, "cached": 0.30, "output": 15.00}


def test_calculate_cost_basic_split():
    result = calculate_cost(1000, 200, 300, "gpt-5.4")
    pricing = PRICING["gpt-5.4"]
    uncached = 1000 - 300
    expected_cost = (
        (uncached / 1_000_000) * pricing["input"]
        + (300 / 1_000_000) * pricing["cached"]
        + (200 / 1_000_000) * pricing["output"]
    )
    assert result["input"] == 1000
    assert result["uncached"] == uncached
    assert result["output"] == 200
    assert result["cached"] == 300
    assert result["cost"] == expected_cost


def test_calculate_cost_uncached_never_negative_when_cached_exceeds_input():
    # cached_tokens > input_tokens should clamp uncached to 0, not go negative.
    result = calculate_cost(100, 50, 500, "gpt-5.4")
    assert result["uncached"] == 0.0
    assert result["cost"] >= 0.0


def test_calculate_cost_zero_tokens():
    result = calculate_cost(0, 0, 0, "gpt-5.4")
    assert result == {"input": 0.0, "uncached": 0.0, "output": 0.0, "cached": 0.0, "cost": 0.0}


def test_calculate_cost_negative_input_clamped():
    # Negative input tokens should not produce a negative uncached share.
    result = calculate_cost(-100, 10, 0, "gpt-5.4")
    assert result["uncached"] == 0.0
    assert result["input"] == -100.0


def test_calculate_cost_unknown_model_uses_fallback_pricing():
    result = calculate_cost(1_000_000, 1_000_000, 0, "totally-unknown-model")
    assert result["cost"] == 3.00 + 15.00
