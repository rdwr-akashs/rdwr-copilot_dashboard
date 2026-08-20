"""Tests for premium_requests.py: multiplier resolution, config precedence, and budget maths."""
from __future__ import annotations

import json
from datetime import datetime

import pytest

from premium_requests import (
    DEFAULT_CRITICAL_THRESHOLD,
    DEFAULT_MULTIPLIER,
    DEFAULT_WARN_THRESHOLD,
    MULTIPLIERS,
    PLAN_ALLOWANCES,
    build_budget,
    get_multiplier,
    load_config,
)


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


# ---------------------------------------------------------------------------
# get_multiplier
# ---------------------------------------------------------------------------

def test_get_multiplier_exact_match():
    assert get_multiplier("gpt-4o") == MULTIPLIERS["gpt-4o"] == 0.0


def test_get_multiplier_case_insensitive_exact_match():
    assert get_multiplier("GPT-4O") == MULTIPLIERS["gpt-4o"]


def test_get_multiplier_prefix_match():
    assert get_multiplier("claude-sonnet-4.5-preview") == MULTIPLIERS["claude-sonnet-4"]


def test_get_multiplier_substring_match():
    assert get_multiplier("copilot/gpt-4o-2024") == MULTIPLIERS["gpt-4o"]


def test_get_multiplier_unknown_model_default():
    assert get_multiplier("some-totally-unknown-model-xyz") == DEFAULT_MULTIPLIER == 1.0


def test_get_multiplier_none_model_default():
    assert get_multiplier(None) == DEFAULT_MULTIPLIER


def test_get_multiplier_custom_table_override():
    custom = {"my-model": 2.5}
    assert get_multiplier("my-model", custom) == 2.5
    # Falls back to the *custom* table's default resolution, not MULTIPLIERS.
    assert get_multiplier("unknown-in-custom-table", custom) == DEFAULT_MULTIPLIER


# ---------------------------------------------------------------------------
# load_config precedence: explicit args > JSON file > env vars > default
# ---------------------------------------------------------------------------

def test_load_config_default_plan_with_nothing_configured(monkeypatch, tmp_path):
    monkeypatch.delenv("COPILOT_PLAN", raising=False)
    monkeypatch.delenv("COPILOT_PREMIUM_QUOTA", raising=False)
    monkeypatch.delenv("COPILOT_PREMIUM_CONFIG", raising=False)
    missing_config = tmp_path / "does-not-exist.json"
    config = load_config(config_path=str(missing_config))
    assert config["plan"] == "pro"
    assert config["allowance"] == PLAN_ALLOWANCES["pro"] == 300
    assert config["configPath"] is None  # no file was actually read


def test_load_config_env_vars_used_when_no_explicit_args_or_file(monkeypatch, tmp_path):
    monkeypatch.setenv("COPILOT_PLAN", "pro_plus")
    monkeypatch.setenv("COPILOT_PREMIUM_QUOTA", "2000")
    monkeypatch.delenv("COPILOT_PREMIUM_CONFIG", raising=False)
    missing_config = tmp_path / "does-not-exist.json"
    config = load_config(config_path=str(missing_config))
    assert config["plan"] == "pro_plus"
    assert config["allowance"] == 2000


def test_load_config_file_overrides_env(monkeypatch, tmp_path):
    monkeypatch.setenv("COPILOT_PLAN", "pro_plus")
    monkeypatch.setenv("COPILOT_PREMIUM_QUOTA", "2000")
    config_file = tmp_path / "premium.json"
    config_file.write_text(json.dumps({"plan": "business", "allowance": 500}), encoding="utf-8")
    config = load_config(config_path=str(config_file))
    assert config["plan"] == "business"
    assert config["allowance"] == 500
    assert config["configPath"] == str(config_file)


def test_load_config_explicit_args_override_file_and_env(monkeypatch, tmp_path):
    monkeypatch.setenv("COPILOT_PLAN", "pro_plus")
    monkeypatch.setenv("COPILOT_PREMIUM_QUOTA", "2000")
    config_file = tmp_path / "premium.json"
    config_file.write_text(json.dumps({"plan": "business", "allowance": 500}), encoding="utf-8")
    config = load_config(plan="enterprise", allowance=12345, config_path=str(config_file))
    assert config["plan"] == "enterprise"
    assert config["allowance"] == 12345


def test_load_config_file_multipliers_merge_over_defaults(tmp_path):
    config_file = tmp_path / "premium.json"
    config_file.write_text(json.dumps({"multipliers": {"gpt-5.4": 0.5, "brand-new-model": 3.0}}), encoding="utf-8")
    config = load_config(config_path=str(config_file))
    assert config["multipliers"]["gpt-5.4"] == 0.5  # overridden
    assert config["multipliers"]["brand-new-model"] == 3.0  # added
    # Untouched defaults survive the merge.
    assert config["multipliers"]["claude-sonnet-4.5"] == MULTIPLIERS["claude-sonnet-4.5"]


def test_load_config_file_thresholds_override_defaults(tmp_path):
    config_file = tmp_path / "premium.json"
    config_file.write_text(json.dumps({"warnThreshold": 60.0, "criticalThreshold": 80.0}), encoding="utf-8")
    config = load_config(config_path=str(config_file))
    assert config["warnThreshold"] == 60.0
    assert config["criticalThreshold"] == 80.0


def test_load_config_missing_or_malformed_file_falls_back_gracefully(tmp_path):
    config_file = tmp_path / "premium.json"
    config_file.write_text("not valid json {{{", encoding="utf-8")
    config = load_config(config_path=str(config_file))
    assert config["plan"] == "pro"
    assert config["warnThreshold"] == DEFAULT_WARN_THRESHOLD
    assert config["criticalThreshold"] == DEFAULT_CRITICAL_THRESHOLD


def test_load_config_plan_name_normalization(tmp_path):
    missing_config = tmp_path / "does-not-exist.json"
    config = load_config(plan="Pro Plus", config_path=str(missing_config))
    assert config["plan"] == "pro_plus"
    assert config["allowance"] == PLAN_ALLOWANCES["pro_plus"]


# ---------------------------------------------------------------------------
# build_budget maths, with a frozen "now" for determinism.
# ---------------------------------------------------------------------------

JUNE_LAST_DAY = datetime(2024, 6, 30, 12, 0, 0)  # June has 30 days -> daysElapsed == daysInMonth
JUNE_MID = datetime(2024, 6, 15, 12, 0, 0)


def _unified_with_monthly_premium(month_key: str, premium_requests: float) -> dict:
    return {"monthly": [{"monthKey": month_key, "premiumRequests": premium_requests}]}


def test_build_budget_days_elapsed_and_days_in_month_frozen_now():
    config = {"plan": "pro", "allowance": 300, "warnThreshold": 75.0, "criticalThreshold": 90.0}
    unified = _unified_with_monthly_premium("2024-06", 0.0)
    budget = build_budget(unified, config, now_ms=_ms(JUNE_MID))
    assert budget["daysInMonth"] == 30
    assert budget["daysElapsed"] == 15


def test_build_budget_basic_maths_with_projection_overrun():
    # used=150 of 300, at day 15 of a 30-day month -> burn rate 10/day,
    # projected month-end = 10 * 30 = 300 = 100% of allowance exactly.
    config = {"plan": "pro", "allowance": 300, "warnThreshold": 75.0, "criticalThreshold": 90.0}
    unified = _unified_with_monthly_premium("2024-06", 150.0)
    budget = build_budget(unified, config, now_ms=_ms(JUNE_MID))

    assert budget["used"] == 150.0
    assert budget["remaining"] == 150.0
    assert budget["percentUsed"] == pytest.approx(50.0)
    assert budget["burnRatePerDay"] == pytest.approx(10.0)
    assert budget["projectedMonthEnd"] == pytest.approx(300.0)
    assert budget["projectedPercent"] == pytest.approx(100.0)
    # projectedPercent >= 100.0 forces "critical" even though percentUsed is only 50%.
    assert budget["status"] == "critical"
    alert_titles = {alert["title"] for alert in budget["alerts"]}
    assert "Projected to exceed monthly allowance" in alert_titles


def test_build_budget_ignores_other_months():
    config = {"plan": "pro", "allowance": 300, "warnThreshold": 75.0, "criticalThreshold": 90.0}
    unified = {"monthly": [
        {"monthKey": "2024-05", "premiumRequests": 999.0},
        {"monthKey": "2024-06", "premiumRequests": 30.0},
    ]}
    budget = build_budget(unified, config, now_ms=_ms(JUNE_MID))
    assert budget["used"] == 30.0  # only the current month's row is used


def test_build_budget_no_monthly_row_for_current_month_yields_zero_used():
    config = {"plan": "pro", "allowance": 300, "warnThreshold": 75.0, "criticalThreshold": 90.0}
    unified = {"monthly": [{"monthKey": "2024-05", "premiumRequests": 500.0}]}
    budget = build_budget(unified, config, now_ms=_ms(JUNE_MID))
    assert budget["used"] == 0.0
    assert budget["status"] == "ok"


@pytest.mark.parametrize(
    ("used", "expected_status"),
    [
        (224.0, "ok"),       # 74.67% - just under the 75% warn threshold
        (225.0, "warn"),     # exactly 75% - warn boundary is inclusive (>=)
        (269.0, "warn"),     # 89.67% - just under the 90% critical threshold
        (270.0, "critical"), # exactly 90% - critical boundary is inclusive (>=)
        (300.0, "critical"), # 100% - fully used
    ],
)
def test_build_budget_status_thresholds_are_inclusive_boundaries(used, expected_status):
    # now = last day of the month -> daysElapsed == daysInMonth, so
    # projectedPercent == percentUsed exactly (no extra crossover from the
    # projection term), isolating the percentUsed threshold logic itself.
    config = {"plan": "pro", "allowance": 300, "warnThreshold": 75.0, "criticalThreshold": 90.0}
    unified = _unified_with_monthly_premium("2024-06", used)
    budget = build_budget(unified, config, now_ms=_ms(JUNE_LAST_DAY))
    assert budget["percentUsed"] == pytest.approx(budget["projectedPercent"])
    assert budget["status"] == expected_status


def test_build_budget_unlimited_allowance_does_not_divide_by_none():
    config = {"plan": "unknown_custom_plan", "allowance": None, "warnThreshold": 75.0, "criticalThreshold": 90.0}
    unified = _unified_with_monthly_premium("2024-06", 42.0)
    budget = build_budget(unified, config, now_ms=_ms(JUNE_MID))

    assert budget["allowance"] is None
    assert budget["remaining"] is None
    assert budget["percentUsed"] == 0.0
    assert budget["projectedPercent"] == 0.0
    assert budget["status"] == "ok"
    # burnRatePerDay is still computed from raw usage (not gated by allowance).
    assert budget["burnRatePerDay"] == pytest.approx(42.0 / 15)
    alert_titles = {alert["title"] for alert in budget["alerts"]}
    assert "No allowance configured" in alert_titles


def test_build_budget_empty_unified_yields_zero_used_without_raising():
    config = {"plan": "pro", "allowance": 300, "warnThreshold": 75.0, "criticalThreshold": 90.0}
    budget = build_budget({}, config, now_ms=_ms(JUNE_MID))
    assert budget["used"] == 0.0
    assert budget["status"] == "ok"

    budget_none_unified = build_budget(None, config, now_ms=_ms(JUNE_MID))
    assert budget_none_unified["used"] == 0.0
