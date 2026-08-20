from __future__ import annotations

"""Premium-request accounting for the GitHub Copilot Dashboard.

GitHub Copilot rations most paid plans in **premium requests**: each
qualifying model call counts as `1 * a per-model multiplier` against a
monthly allowance, with unused capacity typically not rolling over and
overage optionally billed per-request. This module estimates that
accounting locally from parsed usage data.

IMPORTANT: everything here is a **local estimate for planning purposes,
not official GitHub billing**. GitHub is the only source of truth for the
actual premium-request count and remaining allowance for an account
(see the "Copilot" page under github.com/settings/billing, or the
organization/enterprise usage report). The multipliers, plan allowances,
and thresholds below are believed-correct at authoring time but WILL drift
as GitHub changes pricing, and every one of them is user-overridable via
`load_config()` (JSON config file or environment variables) precisely
because this module cannot query GitHub's billing system directly.
"""

import json
import os
from datetime import datetime
from typing import Any

# Per-model premium-request multipliers.
#
# Anchored to GitHub's publicly documented "Requests" multiplier table where
# known (e.g. GPT-4.1/4o/5-mini included at 0x, Claude Haiku family at ~0.33x,
# Claude Sonnet family at 1x, Gemini Flash tiers at 0.25x, Gemini Pro at 1x).
# `model_pricing.PRICING` in this repo also includes several model names
# (claude-sonnet-5/opus-4.6+, gpt-5.2+, gemini-3.x) that are newer than or
# postdate any officially published multiplier table available to the
# author; those are marked below with an explicit "not officially
# documented" comment and a best-guess value based on the model's apparent
# tier (mini/nano/flash => cheaper, standard/pro/sonnet => 1x, opus => cost
# parity with Anthropic's post-4.5 pricing reduction). Override any of these
# via the JSON config file described in `load_config()`.
MULTIPLIERS: dict[str, float] = {
    # Anthropic
    "claude-haiku-4.5": 0.33,       # documented: Haiku-tier models ~1/3x
    "claude-sonnet-4": 1.0,         # documented: Sonnet family 1x
    "claude-sonnet-4.5": 1.0,       # documented: Sonnet family 1x
    "claude-sonnet-4.6": 1.0,       # not officially documented; assumed same tier as Sonnet 4.x
    "claude-sonnet-5": 1.0,         # not officially documented; assumed same tier as Sonnet family
    "claude-opus-4.5": 1.0,         # documented: Anthropic/GitHub reduced Opus 4.5 to 1x (down from 10x for Opus 4/4.1)
    "claude-opus-4.6": 1.0,         # not officially documented; assumed same as Opus 4.5
    "claude-opus-4.7": 1.0,         # not officially documented; assumed same as Opus 4.5
    "claude-opus-4.8": 1.0,         # not officially documented; assumed same as Opus 4.5
    # OpenAI
    "gpt-4.1": 0.0,                 # documented: included in all paid plans
    "gpt-4o": 0.0,                  # documented: included in all paid plans
    "gpt-4o-mini-2024-07-18": 0.0,  # documented: included, mini-tier
    "gpt-5-mini": 0.0,              # documented: included, mini-tier
    "gpt-5.2": 1.0,                 # not officially documented; assumed standard 1x tier like GPT-5
    "gpt-5.2-codex": 1.0,           # not officially documented; assumed standard 1x tier
    "gpt-5.3-codex": 1.0,           # not officially documented; assumed standard 1x tier
    "gpt-5.4": 1.0,                 # not officially documented; assumed standard 1x tier
    "gpt-5.4-mini": 0.33,           # not officially documented; mini-tier assumed cheaper like other *-mini models
    "gpt-5.4-nano": 0.0,            # not officially documented; nano-tier assumed included, like gpt-5-mini
    "gpt-5.5": 1.0,                 # not officially documented; assumed standard 1x tier
    "gpt-5.6-luna": 0.33,           # not officially documented; name suggests a light tier, assumed cheaper
    "gpt-5.6-terra": 1.0,           # not officially documented; assumed standard 1x tier
    "gpt-5.6-sol": 1.0,             # not officially documented; assumed premium 1x tier
    # Google
    "gemini-2.5-pro": 1.0,          # documented: Gemini Pro tier 1x
    "gemini-3-flash": 0.25,         # not officially documented; Flash tiers historically 0.25x
    "gemini-3.1-pro": 1.0,          # not officially documented; assumed Pro-tier 1x
    "gemini-3.5-flash": 0.25,       # not officially documented; Flash tiers historically 0.25x
}

# Applied when a model isn't found by exact/prefix/substring match below.
# 1x is the most common multiplier tier for "standard" models GitHub has
# documented, so it's the safest generic default.
DEFAULT_MULTIPLIER = 1.0

# Monthly premium-request allowances per plan, per GitHub's publicly
# documented plan comparison at authoring time. `None` means unlimited or
# not meaningfully bounded (not currently used, kept for forward-compat).
# These are believed correct but change over time - override via
# `load_config()` (config file / env vars) rather than editing this table.
PLAN_ALLOWANCES: dict[str, int | None] = {
    "free": 50,          # GitHub Copilot Free: 50 premium requests/month
    "pro": 300,           # GitHub Copilot Pro: 300 premium requests/month
    "pro_plus": 1500,     # GitHub Copilot Pro+: 1,500 premium requests/month
    "business": 300,      # GitHub Copilot Business: 300 premium requests/user/month
    "enterprise": 1000,   # GitHub Copilot Enterprise: 1,000 premium requests/user/month
}

DEFAULT_PLAN = "pro"
DEFAULT_WARN_THRESHOLD = 75.0
DEFAULT_CRITICAL_THRESHOLD = 90.0

_CONFIG_ENV_VAR = "COPILOT_PREMIUM_CONFIG"
_DEFAULT_CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".copilot-dashboard", "premium.json")


def get_multiplier(model_name: str | None, multipliers: dict[str, float] | None = None) -> float:
    """Resolve a model's premium-request multiplier.

    Uses the same tolerant exact -> prefix -> substring -> default matching
    strategy as `model_pricing.get_pricing`, for consistency between cost
    and premium-request estimates.
    """
    table = multipliers if multipliers is not None else MULTIPLIERS
    model_lower = (model_name or "").lower()
    if model_lower in table:
        return table[model_lower]
    for key, multiplier in table.items():
        if model_lower.startswith(key) or key in model_lower:
            return multiplier
    return DEFAULT_MULTIPLIER


def _read_config_file(path: str | None) -> dict[str, Any]:
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def load_config(
    plan: str | None = None,
    allowance: int | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    """Resolve the plan/allowance/multiplier/threshold configuration.

    Priority order (highest wins): explicit function arguments > JSON config
    file (`config_path`, else `$COPILOT_PREMIUM_CONFIG`, else
    `~/.copilot-dashboard/premium.json`) > environment variables
    (`COPILOT_PLAN`, `COPILOT_PREMIUM_QUOTA`) > built-in default plan
    ("pro"). The JSON config file may also override `multipliers` (a dict
    merged on top of `MULTIPLIERS`) and `warnThreshold` / `criticalThreshold`
    (percent-used alert thresholds).

    This is the single override point for every number in this module - none
    of the constants above should be treated as authoritative without
    checking this function's resolved output first.
    """
    resolved_path = config_path or os.environ.get(_CONFIG_ENV_VAR) or _DEFAULT_CONFIG_PATH
    file_config = _read_config_file(resolved_path)

    resolved_plan = (
        plan
        or file_config.get("plan")
        or os.environ.get("COPILOT_PLAN")
        or DEFAULT_PLAN
    )
    resolved_plan = str(resolved_plan).strip().lower().replace("-", "_").replace(" ", "_")

    env_quota = os.environ.get("COPILOT_PREMIUM_QUOTA")
    resolved_allowance: int | None
    if allowance is not None:
        resolved_allowance = int(allowance)
    elif "allowance" in file_config and file_config.get("allowance") is not None:
        resolved_allowance = int(file_config["allowance"])
    elif env_quota:
        try:
            resolved_allowance = int(env_quota)
        except Exception:
            resolved_allowance = PLAN_ALLOWANCES.get(resolved_plan)
    else:
        resolved_allowance = PLAN_ALLOWANCES.get(resolved_plan)

    multipliers = dict(MULTIPLIERS)
    file_multipliers = file_config.get("multipliers")
    if isinstance(file_multipliers, dict):
        for key, value in file_multipliers.items():
            try:
                multipliers[str(key).lower()] = float(value)
            except Exception:
                continue

    warn_threshold = float(file_config.get("warnThreshold", DEFAULT_WARN_THRESHOLD) or DEFAULT_WARN_THRESHOLD)
    critical_threshold = float(file_config.get("criticalThreshold", DEFAULT_CRITICAL_THRESHOLD) or DEFAULT_CRITICAL_THRESHOLD)

    return {
        "plan": resolved_plan,
        "allowance": resolved_allowance,
        "multipliers": multipliers,
        "warnThreshold": warn_threshold,
        "criticalThreshold": critical_threshold,
        "configPath": resolved_path if file_config else None,
    }


def _days_in_month(dt: datetime) -> int:
    if dt.month == 12:
        next_month = dt.replace(year=dt.year + 1, month=1, day=1)
    else:
        next_month = dt.replace(month=dt.month + 1, day=1)
    return (next_month - dt.replace(day=1)).days


# Severity ranking shared by `status` and every alert's `severity`, so the
# two can never disagree (see `_severity_for_percent` / `build_budget`).
_SEVERITY_RANK = {"ok": 0, "info": 0, "warn": 1, "critical": 2}


def _severity_for_percent(percent: float, warn_threshold: float, critical_threshold: float) -> str:
    """Map a usage percentage to one severity tier.

    This is the ONE formula used for both the current-usage severity and the
    projected-month-end severity in `build_budget` - `status` is derived from
    the same two calls to this function that produce the alert severities,
    so they cannot silently disagree.
    """
    if percent >= critical_threshold:
        return "critical"
    if percent >= warn_threshold:
        return "warn"
    return "ok"


def _max_severity(a: str, b: str) -> str:
    return a if _SEVERITY_RANK.get(a, 0) >= _SEVERITY_RANK.get(b, 0) else b


def build_budget(unified: dict[str, Any], config: dict[str, Any], now_ms: float | int | None = None) -> dict[str, Any]:
    """Estimate this calendar month's premium-request budget status.

    Reads `unified["monthly"]` (from `usage_model.build_unified`) for the
    current-month premium-request total across both chat and CLI sources,
    then projects month-end usage from the current burn rate. This is a
    local estimate only - see the module docstring.

    Severity reconciliation (status vs. alerts)
    --------------------------------------------
    `status` and every alert's `severity` are derived from the SAME
    `_severity_for_percent()` formula, applied to two inputs: the *actual*
    percent used so far this month (`percentUsed`), and the *projected*
    month-end percent from the current burn rate (`projectedPercent`).
    `status` is always `max(current_severity, projected_severity)` (ranked
    ok < warn < critical), and every alert emitted carries exactly one of
    those two same severities - so `status` can never read "critical" while
    every alert says "warn", or vice-versa. Alert text is explicit about
    which of the two ("used so far" vs. "projected") it is describing, so
    a "warn" alert about a *projected* overrun next to an "ok" actual-usage
    figure is never mistaken for a contradiction.

    Early-month low-confidence projections
    ----------------------------------------
    Extrapolating a full month from 1-2 days of burn rate is unreliable (one
    heavy day looks like a monthly trend). `projectionConfidence` reports
    this ("low" for `daysElapsed<=2`, "medium" for `<=7`, else "high"). A
    "low"-confidence projection is capped at "warn" for `status`/alert
    purposes - it can never *alone* push `status` to "critical" - even
    though the raw `projectedMonthEnd`/`projectedPercent` numbers are still
    reported unclamped as context. Actual usage (`percentUsed`) is never
    dampened this way.

    Over-quota accounting
    ------------------------
    `remaining` is clamped to 0 once usage meets or exceeds the allowance
    (never rendered as a negative number); the amount over is reported
    separately as `overage`. Exceeding the allowance is the ordinary case on
    some machines/plans, not a corner case to hide behind a negative number.
    """
    now = datetime.fromtimestamp((now_ms or 0) / 1000.0) if now_ms else datetime.now()
    current_month_key = now.strftime("%Y-%m")

    used = 0.0
    for row in (unified or {}).get("monthly", []) or []:
        if row.get("monthKey") == current_month_key:
            used = float(row.get("premiumRequests", 0.0) or 0.0)
            break

    allowance = config.get("allowance")
    days_in_month = _days_in_month(now)
    days_elapsed = max(1, now.day)

    has_allowance = allowance is not None and allowance > 0
    if has_allowance:
        remaining = max(0.0, allowance - used)
        overage = max(0.0, used - allowance)
        percent_used = used / allowance * 100.0
    else:
        remaining = None
        overage = 0.0
        percent_used = 0.0

    burn_rate_per_day = used / days_elapsed if days_elapsed else 0.0
    projected_month_end = burn_rate_per_day * days_in_month
    projected_percent = (projected_month_end / allowance * 100.0) if has_allowance else 0.0

    if days_elapsed <= 2:
        projection_confidence = "low"
    elif days_elapsed <= 7:
        projection_confidence = "medium"
    else:
        projection_confidence = "high"

    warn_threshold = float(config.get("warnThreshold", DEFAULT_WARN_THRESHOLD))
    critical_threshold = float(config.get("criticalThreshold", DEFAULT_CRITICAL_THRESHOLD))

    status = "ok"
    alerts: list[dict[str, str]] = []
    if has_allowance:
        current_severity = _severity_for_percent(percent_used, warn_threshold, critical_threshold)
        projected_severity = _severity_for_percent(projected_percent, warn_threshold, critical_threshold)
        # Dampen a low-confidence projection so a single heavy early-month
        # day can't unilaterally declare "critical" - see docstring above.
        if projection_confidence == "low" and projected_severity == "critical":
            projected_severity = "warn"

        status = _max_severity(current_severity, projected_severity)

        if current_severity != "ok":
            alerts.append({
                "severity": current_severity,
                "title": "Premium request usage critical" if current_severity == "critical" else "Premium request usage high",
                "detail": f"{used:.0f} of {allowance:.0f} premium requests used so far this month ({percent_used:.0f}%).",
            })

        # Only surface the projection as its own alert when it says more
        # than the current-usage alert already does (i.e. the projection is
        # worse than where things stand today).
        if projected_severity != "ok" and projected_percent > percent_used + 1e-9:
            confidence_note = (
                f" (low-confidence estimate based on only {days_elapsed} day(s) of data this month)"
                if projection_confidence == "low" else ""
            )
            alerts.append({
                "severity": projected_severity,
                "title": "Projected to exceed monthly allowance" if projected_percent >= 100.0 else "Projected usage trending high",
                "detail": (
                    f"At the current burn rate (~{burn_rate_per_day:.1f}/day) usage is projected to reach "
                    f"{projected_month_end:.0f} by month end ({projected_percent:.0f}% of the {allowance:.0f}-request "
                    f"allowance){confidence_note}."
                ),
            })
    else:
        alerts.append({
            "severity": "info",
            "title": "No allowance configured",
            "detail": "Plan allowance is unknown/unlimited; usage is tracked but not compared against a budget.",
        })

    return {
        "plan": config.get("plan"),
        "allowance": allowance,
        "used": used,
        "remaining": remaining,
        "overage": overage,
        "percentUsed": percent_used,
        "daysElapsed": days_elapsed,
        "daysInMonth": days_in_month,
        "burnRatePerDay": burn_rate_per_day,
        "projectedMonthEnd": projected_month_end,
        "projectedPercent": projected_percent,
        "projectionConfidence": projection_confidence,
        "status": status,
        "alerts": alerts,
    }
