"""Tests for model_pricing.py: get_pricing() lookup and calculate_cost() maths."""
from __future__ import annotations

import pytest

from model_pricing import (
    PRICING,
    TOKEN_TYPES,
    cache_write_rate,
    calculate_cost,
    cost_from_token_counts,
    get_pricing,
    get_rates,
    nano_aiu_to_usd,
    split_prompt_tokens,
    usd_to_nano_aiu,
)


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
    assert result == {
        "input": 0.0,
        "uncached": 0.0,
        "output": 0.0,
        "cached": 0.0,
        "cacheWrite": 0.0,
        "cost": 0.0,
        "costByType": {"input": 0.0, "cache_read": 0.0, "cache_write": 0.0, "output": 0.0},
        "rates": {"input": 2.50, "cache_read": 0.25, "cache_write": 0.0, "output": 15.00},
        "tier": "default",
    }


def test_calculate_cost_negative_input_clamped():
    # Negative input tokens should not produce a negative uncached share.
    result = calculate_cost(-100, 10, 0, "gpt-5.4")
    assert result["uncached"] == 0.0
    assert result["input"] == -100.0


def test_calculate_cost_unknown_model_uses_fallback_pricing():
    result = calculate_cost(1_000_000, 1_000_000, 0, "totally-unknown-model")
    assert result["cost"] == 3.00 + 15.00


# --------------------------------------------------------------------------
# Cache writes
# --------------------------------------------------------------------------


def test_cache_write_rate_matches_published_table():
    # Anthropic publishes cache write at 1.25x input.
    assert cache_write_rate("claude-sonnet-4.5") == 3.75
    assert cache_write_rate("claude-opus-5") == 6.25


def test_cache_write_rate_is_zero_when_not_applicable():
    """Models whose pricing row prints "Not applicable" for cache write are
    billed nothing for those tokens - 0.0 is the correct rate, not a fallback
    multiple of the input rate."""
    assert cache_write_rate("gpt-5.4") == 0.0
    assert cache_write_rate("gemini-3.1-pro") == 0.0
    assert cache_write_rate("totally-unknown-model") == 0.0
    assert cache_write_rate(None) == 0.0


def test_cache_writes_are_carved_out_of_the_prompt_not_added_to_it():
    """`input_tokens` is all-inclusive: prompt = uncached + cache_read + cache_write.
    Charging the whole prompt at the input rate on top of the cache lines would
    double-bill it."""
    result = calculate_cost(1000, 200, 100, "claude-sonnet-4.5", cache_write_tokens=50)
    assert result["uncached"] == 850
    assert result["cached"] == 100
    assert result["cacheWrite"] == 50
    expected = (
        850 / 1_000_000 * 3.00
        + 100 / 1_000_000 * 0.30
        + 50 / 1_000_000 * 3.75
        + 200 / 1_000_000 * 15.00
    )
    assert result["cost"] == pytest.approx(expected)
    assert sum(result["costByType"].values()) == pytest.approx(result["cost"])


def test_cache_writes_cost_more_than_the_input_rate_would():
    """The old formula billed cache writes at the input rate; for Anthropic
    models that undercounts by 25% of those tokens."""
    with_writes = calculate_cost(1000, 0, 0, "claude-sonnet-4.5", cache_write_tokens=200)
    as_plain_input = calculate_cost(1000, 0, 0, "claude-sonnet-4.5")
    assert with_writes["cost"] > as_plain_input["cost"]
    assert with_writes["cost"] - as_plain_input["cost"] == pytest.approx(200 / 1_000_000 * (3.75 - 3.00))


def test_split_prompt_tokens_partitions_the_prompt():
    assert split_prompt_tokens(1000, 100, 50) == {"input": 850, "cache_read": 100, "cache_write": 50}


def test_split_prompt_tokens_clamps_and_never_goes_negative():
    assert split_prompt_tokens(100, 500, 200) == {"input": 0.0, "cache_read": 500, "cache_write": 200}
    assert split_prompt_tokens(0, -5, -5) == {"input": 0.0, "cache_read": 0.0, "cache_write": 0.0}


# --------------------------------------------------------------------------
# Long-context tiers
# --------------------------------------------------------------------------


def test_default_tier_used_below_the_long_context_threshold():
    rates = get_rates("gpt-5.4", prompt_tokens=271_999)
    assert rates["tier"] == "default"
    assert rates["input"] == 2.50
    assert rates["output"] == 15.00


def test_long_context_tier_used_above_the_threshold():
    rates = get_rates("gpt-5.4", prompt_tokens=272_001)
    assert rates["tier"] == "long"
    assert rates["input"] == 5.00
    assert rates["cache_read"] == 0.50
    assert rates["output"] == 22.50


def test_long_context_threshold_is_exclusive():
    # "Above 272K" - exactly at the threshold is still the default tier.
    assert get_rates("gpt-5.4", prompt_tokens=272_000)["tier"] == "default"


def test_unknown_prompt_size_keeps_the_default_tier():
    """Callers that cannot supply a prompt size must not be silently upgraded
    to long-context rates."""
    assert get_rates("gpt-5.4")["tier"] == "default"
    assert get_rates("gpt-5.4", prompt_tokens=None)["tier"] == "default"


def test_long_context_row_without_cache_write_keeps_zero_rate():
    """gpt-5.4's long-context row prints no cache-write rate, so cache writes
    stay unbilled at that tier rather than inheriting a nearby number."""
    assert get_rates("gpt-5.4", prompt_tokens=300_000)["cache_write"] == 0.0


def test_long_context_row_with_cache_write_uses_the_tier_rate():
    assert get_rates("gpt-5.6-sol", prompt_tokens=300_000)["cache_write"] == 5.00
    assert get_rates("gpt-5.6-sol", prompt_tokens=1_000)["cache_write"] == 2.50


def test_models_without_a_long_context_tier_are_flat():
    assert get_rates("claude-sonnet-4.5", prompt_tokens=5_000_000)["tier"] == "default"
    assert get_rates("claude-sonnet-4.5", prompt_tokens=5_000_000)["input"] == 3.00


def test_calculate_cost_applies_the_long_context_tier():
    result = calculate_cost(300_000, 1_000, 0, "gpt-5.4")
    assert result["tier"] == "long"
    assert result["cost"] == pytest.approx(300_000 / 1_000_000 * 5.00 + 1_000 / 1_000_000 * 22.50)


# --------------------------------------------------------------------------
# Explicit rates (what GitHub actually billed) override the table
# --------------------------------------------------------------------------


def test_supplied_rates_override_the_published_table():
    """The CLI reads the rates GitHub applied out of `token_details_json`; those
    must win over this repo's table, which is only a fallback."""
    rates = {"input": 1.00, "cache_read": 0.10, "cache_write": 1.25, "output": 5.00}
    result = calculate_cost(1000, 100, 200, "claude-sonnet-4.5", cache_write_tokens=100, rates=rates)
    assert result["rates"] == rates
    assert result["cost"] == pytest.approx(
        700 / 1_000_000 * 1.00 + 200 / 1_000_000 * 0.10 + 100 / 1_000_000 * 1.25 + 100 / 1_000_000 * 5.00
    )


def test_cost_from_token_counts_sums_to_by_type():
    counts = {"input": 1000, "cache_read": 2000, "cache_write": 300, "output": 400}
    priced = cost_from_token_counts(counts, "claude-sonnet-4.5")
    assert sum(priced["byType"].values()) == pytest.approx(priced["cost"])
    assert set(priced["byType"]) == set(TOKEN_TYPES)


# --------------------------------------------------------------------------
# AI credit conversion
# --------------------------------------------------------------------------


def test_nano_aiu_conversion_roundtrips():
    # 1 AI credit = $0.01 = 1e9 nano AIU.
    assert nano_aiu_to_usd(1_000_000_000) == pytest.approx(0.01)
    assert usd_to_nano_aiu(0.01) == pytest.approx(1_000_000_000)
    assert nano_aiu_to_usd(usd_to_nano_aiu(1.23)) == pytest.approx(1.23)


def test_nano_aiu_handles_none_and_zero():
    assert nano_aiu_to_usd(None) == 0.0
    assert nano_aiu_to_usd(0) == 0.0
    assert usd_to_nano_aiu(None) == 0.0


# --------------------------------------------------------------------------
# Table values that were wrong and must not regress
# --------------------------------------------------------------------------


def test_gpt_5_6_sol_promotional_rates():
    """Pinned against the official pricing page (verified 2026-08-24). The repo
    previously carried 5.00/0.50/30.00 here, 2.5-3x the real rate."""
    assert PRICING["gpt-5.6-sol"] == {"input": 2.00, "cached": 0.20, "output": 10.00}
    assert cache_write_rate("gpt-5.6-sol") == 2.50


def test_fast_mode_is_not_swallowed_by_the_standard_opus_key():
    """Longest-key-first matching: `claude-opus-4.8-fast` bills at 2x standard
    Opus, and a prefix match on `claude-opus-4.8` would halve it."""
    assert get_pricing("claude-opus-4.8-fast")["input"] == 10.00
    assert get_pricing("claude-opus-4.8")["input"] == 5.00
    assert cache_write_rate("claude-opus-4.8-fast") == 12.50
