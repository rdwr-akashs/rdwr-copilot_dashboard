from __future__ import annotations

"""Copilot usage-allowance accounting for the GitHub Copilot Dashboard.

GitHub now rations paid Copilot plans in **AI credits**, not premium
requests: 1 credit = $0.01 USD of model usage, priced off the per-token
rates in `model_pricing.PRICING`. A plan's monthly allowance is a credit
balance, so the quantity to compare against it is the *cost* of the
month's usage x 100 - not a count of calls. That is what `build_budget()`
does.

Premium requests are LEGACY. GitHub retains request-based billing only
for annual Pro/Pro+ subscriptions purchased before the credit model, where
one premium request is charged per *user prompt* (not per model call, and
not for the agent's own follow-up tool calls) multiplied by a per-model
multiplier. `MULTIPLIERS` / `LEGACY_PLAN_REQUEST_ALLOWANCES` and the
`legacyRequests` sub-block of `build_budget()`'s result exist for those
accounts and for reading historical data; they are not the primary meter.

SOURCE OF TRUTH for the numbers below:
https://docs.github.com/en/copilot/concepts/billing (credits, plan
allowances) and .../copilot/reference/copilot-billing/models-and-pricing
(per-token rates). Verified 2026-08-21.

IMPORTANT: everything here is a **local estimate for planning purposes,
not official GitHub billing**. GitHub is the only source of truth for an
account's actual credit consumption and remaining allowance (see the
"Copilot" page under github.com/settings/billing, or the
organization/enterprise usage report). The allowances, multipliers, and
thresholds below are believed-correct at authoring time but WILL drift as
GitHub changes pricing, and every one of them is user-overridable via
`load_config()` (JSON config file or environment variables) precisely
because this module cannot query GitHub's billing system directly.
"""

import json
import os
from datetime import datetime
from typing import Any

from model_pricing import match_keys

# Per-model premium-request multipliers. LEGACY - applies only to annual
# Pro/Pro+ subscriptions still billed in premium requests (see module
# docstring). Credit-billed plans ignore these entirely and are metered on
# cost; a model missing from this table is not a bug for those plans.
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

# AI credits are the unit every allowance below is denominated in, and
# `1 credit = $0.01 USD` is the conversion GitHub bills at. Model usage is
# priced per-token (model_pricing.PRICING), so a month's credit consumption
# is that month's dollar cost x 100.
CREDIT_USD = 0.01
CREDITS_PER_USD = 1.0 / CREDIT_USD  # 100.0
ALLOWANCE_UNIT = "credits"


def usd_to_credits(usd: float) -> float:
    """Convert a USD model-usage cost into AI credits (1 credit = $0.01)."""
    return float(usd or 0.0) * CREDITS_PER_USD


def credits_to_usd(credits: float) -> float:
    """Convert AI credits back into USD (1 credit = $0.01)."""
    return float(credits or 0.0) * CREDIT_USD


# Monthly AI-credit allowances per plan, per GitHub's published plan
# comparison. Each figure is the total spendable in a month = the included
# monthly credits plus the plan's flex/overage credits, since both draw down
# before usage is refused or billed on. `None` means "no credit allowance
# documented" - usage is then tracked but not budget-compared.
#
# These are believed correct but change over time - override via
# `load_config()` (config file / env vars) rather than editing this table.
PLAN_CREDIT_ALLOWANCES: dict[str, int | None] = {
    # Copilot Free has no credit allowance; it is capped in completions and
    # chat requests instead, which this dashboard cannot budget against.
    "free": None,
    "pro": 1500,          # Pro: 1,000 included + 500 flex
    "student": 1500,      # Pro, free for verified students/teachers - same allowance
    "pro_plus": 7000,     # Pro+: 3,900 included + 3,100 flex
    "max": 20000,         # Max: 10,000 included + 10,000 flex
    "business": 1900,     # Business: 1,900 credits/user/month
    "enterprise": 3900,   # Enterprise: 3,900 credits/user/month
}

# Back-compat alias. Both names mean AI credits; `PLAN_ALLOWANCES` is kept
# because `dashboard_core` ships it to the frontend as `premium.planAllowances`.
PLAN_ALLOWANCES = PLAN_CREDIT_ALLOWANCES

# LEGACY monthly premium-REQUEST allowances, for accounts still on annual
# request-billed Pro/Pro+ and for interpreting historical data. Not used to
# resolve `config["allowance"]` - that is credits (above).
LEGACY_PLAN_REQUEST_ALLOWANCES: dict[str, int | None] = {
    "free": 50,           # Copilot Free: 50 premium requests/month
    "pro": 300,           # Pro: 300 premium requests/month
    "pro_plus": 1500,     # Pro+: 1,500 premium requests/month
    "business": 300,      # Business: 300 premium requests/user/month
    "enterprise": 1000,   # Enterprise: 1,000 premium requests/user/month
}

DEFAULT_PLAN = "pro"
DEFAULT_WARN_THRESHOLD = 75.0
DEFAULT_CRITICAL_THRESHOLD = 90.0

_CONFIG_ENV_VAR = "COPILOT_PREMIUM_CONFIG"
_DEFAULT_CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".copilot-dashboard", "premium.json")


def get_multiplier(model_name: str | None, multipliers: dict[str, float] | None = None) -> float:
    """Resolve a model's legacy premium-request multiplier.

    Uses the same tolerant exact -> prefix -> substring -> default matching
    strategy as `model_pricing.get_pricing`, including its longest-key-first
    ordering (`model_pricing.match_keys`), so cost and premium-request
    estimates always resolve the same telemetry name to the same model rather
    than disagreeing on a prefix collision.
    """
    table = multipliers if multipliers is not None else MULTIPLIERS
    model_lower = (model_name or "").lower()
    if model_lower in table:
        return table[model_lower]
    for key in match_keys(table):
        if model_lower.startswith(key) or key in model_lower:
            return table[key]
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

    `allowance` is denominated in AI CREDITS (1 credit = $0.01 of model
    usage), matching `PLAN_CREDIT_ALLOWANCES` - not in premium requests.

    Priority order (highest wins): explicit function arguments > JSON config
    file (`config_path`, else `$COPILOT_PREMIUM_CONFIG`, else
    `~/.copilot-dashboard/premium.json`) > environment variables
    (`COPILOT_PLAN`, and `COPILOT_CREDIT_QUOTA` or its older spelling
    `COPILOT_PREMIUM_QUOTA`) > built-in default plan ("pro"). The JSON config
    file may also override `multipliers` (a dict merged on top of
    `MULTIPLIERS`, legacy premium-request accounting only) and
    `warnThreshold` / `criticalThreshold` (percent-used alert thresholds).

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

    env_quota = os.environ.get("COPILOT_CREDIT_QUOTA") or os.environ.get("COPILOT_PREMIUM_QUOTA")
    resolved_allowance: int | None
    if allowance is not None:
        resolved_allowance = int(allowance)
    elif "allowance" in file_config and file_config.get("allowance") is not None:
        resolved_allowance = int(file_config["allowance"])
    elif env_quota:
        try:
            resolved_allowance = int(env_quota)
        except Exception:
            resolved_allowance = PLAN_CREDIT_ALLOWANCES.get(resolved_plan)
    else:
        resolved_allowance = PLAN_CREDIT_ALLOWANCES.get(resolved_plan)

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
        "allowanceUnit": ALLOWANCE_UNIT,
        "creditUsd": CREDIT_USD,
        "legacyRequestAllowance": LEGACY_PLAN_REQUEST_ALLOWANCES.get(resolved_plan),
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
    """Estimate this calendar month's AI-credit budget status.

    Reads `unified["monthly"]` (from `usage_model.build_unified`) for the
    current month's total across both chat and CLI sources, then projects
    month-end usage from the current burn rate. This is a local estimate
    only - see the module docstring.

    Unit: AI CREDITS
    ------------------
    `used` / `remaining` / `overage` / `burnRatePerDay` / `projectedMonthEnd`
    are all credits, derived as `billed cost in USD x 100` (1 credit =
    $0.01), because that is how GitHub meters a credit-billed plan - by the
    dollar value of tokens consumed, not by a count of calls. `usedUsd` and
    `allowanceUsd` report the same figures in dollars for readability, and
    `unit`/`creditUsd` state the convention explicitly so no consumer has to
    infer it.

    The month's *billed* cost is used in preference to the attributed cost:
    billing follows the tokens actually sent to the model, and prompt-growth
    attribution is a presentation-side reallocation of the same spend.
    Attributed cost is the fallback only when a row carries no billed cost.

    Legacy premium requests
    -------------------------
    `legacyRequests` carries the multiplier-weighted premium-request estimate
    that used to drive this budget, for accounts still on annual
    request-billed Pro/Pro+ and for reading historical data. It is reported,
    never used to compute `status` or `alerts`.

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

    used_usd = 0.0
    legacy_requests = 0.0
    for row in (unified or {}).get("monthly", []) or []:
        if row.get("monthKey") == current_month_key:
            billed_cost = float(((row.get("billed") or {}).get("cost", 0.0)) or 0.0)
            attributed_cost = float(((row.get("attributed") or {}).get("cost", 0.0)) or 0.0)
            used_usd = billed_cost or attributed_cost
            legacy_requests = float(row.get("premiumRequests", 0.0) or 0.0)
            break

    used = usd_to_credits(used_usd)

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
                "title": "AI credit usage critical" if current_severity == "critical" else "AI credit usage high",
                "detail": (
                    f"{used:.0f} of {allowance:.0f} AI credits used so far this month "
                    f"({percent_used:.0f}%) - about ${used_usd:.2f} of model usage."
                ),
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
                    f"At the current burn rate (~{burn_rate_per_day:.1f} credits/day) usage is projected to reach "
                    f"{projected_month_end:.0f} credits by month end ({projected_percent:.0f}% of the "
                    f"{allowance:.0f}-credit allowance){confidence_note}."
                ),
            })
    else:
        alerts.append({
            "severity": "info",
            "title": "No allowance configured",
            "detail": "Plan credit allowance is unknown/unlimited; usage is tracked but not compared against a budget.",
        })

    return {
        "plan": config.get("plan"),
        "unit": ALLOWANCE_UNIT,
        "creditUsd": CREDIT_USD,
        "allowance": allowance,
        "allowanceUsd": credits_to_usd(allowance) if allowance is not None else None,
        "used": used,
        "usedUsd": used_usd,
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
        # Legacy, reported only - see the docstring. `allowance` here is the
        # request-based plan quota, which is NOT comparable to the credit
        # figures above; keep the two units visibly separate.
        "legacyRequests": {
            "used": legacy_requests,
            "allowance": config.get("legacyRequestAllowance", LEGACY_PLAN_REQUEST_ALLOWANCES.get(str(config.get("plan") or ""))),
            "unit": "premium requests",
            "note": (
                "Multiplier-weighted premium-request estimate. Applies only to annual "
                "Pro/Pro+ subscriptions still billed in requests; credit-billed plans are "
                "metered on the credit figures above."
            ),
        },
    }
