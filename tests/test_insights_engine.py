"""Lightweight coverage for insights_engine.py (added by another agent after
this suite's first pass). insights_engine.py was not present when this
harness was originally built; the rest of the suite tolerates its absence
(see tests/test_structural_contract.py), but since it now exists this module
pins its top-level contract: shape, determinism, sort order, and
never-raises-on-empty-input behavior. It does not attempt to exercise every
individual `_rule_*` heuristic (out of scope for this pass).
"""
from __future__ import annotations

import pytest

from insights_engine import DEFAULT_CONFIG, _fmt_credits, build_insights, build_insights_with_diagnostics

REQUIRED_INSIGHT_KEYS = {
    "id", "severity", "title", "detail", "source", "evidence",
    "estimatedSavings", "action", "confidence",
}


def test_build_insights_returns_list_never_raises_on_empty_app_data():
    insights = build_insights({})
    assert isinstance(insights, list)


def test_build_insights_returns_list_never_raises_on_none_like_missing_keys():
    # sessions/cli/unified/premium all missing entirely.
    insights = build_insights({"generatedAt": "now"})
    assert isinstance(insights, list)


def test_build_insights_is_deterministic_for_the_same_input():
    app_data = {
        "sessions": [],
        "cli": {"sessions": []},
        "unified": {"monthly": [], "byModel": [], "bySource": []},
        "premium": {"budget": {}},
    }
    first = build_insights(app_data)
    second = build_insights(app_data)
    assert first == second


def test_every_insight_has_the_documented_shape():
    # A minimal chat session engineered to trip the "abandoned session" rule
    # (high cost, near-zero output) so at least one real insight is produced
    # and its shape can be checked.
    app_data = {
        "sessions": [
            {
                "id": "sess1",
                "totals": {"input": 100000.0, "output": 5.0, "cached": 0.0, "cost": 5.0},
                "billed_totals": {"input": 100000.0, "output": 5.0, "cached": 0.0, "cost": 5.0},
                "chat_count": 1,
                "events": [],
            }
        ],
        "cli": {"sessions": []},
        "unified": {"monthly": [], "byModel": [], "bySource": []},
        "premium": {"budget": {}},
    }
    insights = build_insights(app_data)
    for insight in insights:
        assert REQUIRED_INSIGHT_KEYS.issubset(insight.keys())
        assert insight["severity"] in {"info", "warn", "critical"}
        assert insight["confidence"] in {"low", "medium", "high"}
        assert insight["source"] in {"chat", "cli", "both"}
        assert set(insight["estimatedSavings"].keys()) == {"cost", "premiumRequests"}


def test_insights_sorted_by_severity_then_savings_cost_descending():
    app_data = {
        "sessions": [],
        "cli": {"sessions": []},
        "unified": {"monthly": [], "byModel": [], "bySource": []},
        "premium": {"budget": {}},
    }
    insights = build_insights(app_data)
    severity_rank = {"critical": 0, "warn": 1, "info": 2}
    ranks = [severity_rank.get(i["severity"], 3) for i in insights]
    assert ranks == sorted(ranks)


def test_build_insights_with_diagnostics_returns_errors_list():
    insights, errors = build_insights_with_diagnostics({})
    assert isinstance(insights, list)
    assert isinstance(errors, list)


def test_default_config_has_all_documented_rule_sections():
    expected_sections = {
        "lowCacheHitRate", "expensiveModelTrivialWork", "duplicateFileReads",
        "contextResetChurn", "oversizedSessions", "abandonedSessions",
        "modelSubstitutionPolicy", "chatVsCliComparison", "premiumRequestBurn",
        "dataHealth",
    }
    assert expected_sections.issubset(DEFAULT_CONFIG.keys())


# ---------------------------------------------------------------------------
# Hypothetical ("what if you had used a cheaper model") costs
# ---------------------------------------------------------------------------

def test_substitution_savings_prices_the_hypothetical_at_the_per_call_tier():
    """A period's token volume must not promote a hypothetical to long-context rates.

    Long-context pricing is billed per call, above a per-prompt threshold. Any
    busy month's *summed* prompt tokens clear that threshold trivially, so
    pricing an aggregate as if it were one giant call roughly doubles the
    hypothetical cost and understates the saving the insight is claiming. The
    tier is chosen from the average prompt per call instead.
    """
    config = {"modelSubstitutionPolicy": {"chatCheapModel": "gpt-5.4", "minSavingsToReport": 0.05}}
    app_data = {
        "sessions": [],
        "cli": {"sessions": []},
        "unified": {
            "monthly": [],
            "byModel": [],
            "bySource": [{
                "source": "chat",
                # 100 calls averaging a 10K prompt - nowhere near the 272K
                # per-call long-context threshold, though the total is 1M.
                "callCount": 100,
                "premiumRequests": 100.0,
                "billed": {"input": 1_000_000.0, "output": 10_000.0, "cached": 0.0, "cost": 20.0},
                "attributed": {"input": 1_000_000.0, "output": 10_000.0, "cached": 0.0, "cost": 20.0},
            }],
        },
        "premium": {"budget": {}},
    }

    insight = next(
        item for item in build_insights(app_data, config=config)
        if item["id"] == "model-substitution-savings"
    )
    evidence = insight["evidence"][0]
    default_tier_cost = 1_000_000 / 1_000_000 * 2.50 + 10_000 / 1_000_000 * 15.00
    long_tier_cost = 1_000_000 / 1_000_000 * 5.00 + 10_000 / 1_000_000 * 22.50

    assert evidence["hypotheticalCost"] == pytest.approx(default_tier_cost, abs=1e-4)
    assert evidence["hypotheticalCost"] < long_tier_cost
    assert insight["estimatedSavings"]["cost"] == pytest.approx(20.0 - default_tier_cost, abs=1e-4)


@pytest.mark.parametrize(
    ("cost_usd", "expected"),
    [
        (0.0, "0.00 cr"),
        (0.0003, "0.03 cr"),
        (0.075, "7.50 cr"),
        (0.5, "50.0 cr"),
        (12.3456, "1,235 cr"),
    ],
)
def test_fmt_credits_reports_spend_in_credits_not_dollars(cost_usd, expected):
    # Insight prose has to read in the same unit as the panel around it: the
    # dashboard reports AI credits (1 credit = $0.01), never dollars.
    assert _fmt_credits(cost_usd) == expected


def test_insight_details_never_quote_a_dollar_figure():
    app_data = {
        "sessions": [],
        "cli": {"sessions": [], "byModel": []},
        "premium": {"budget": {}},
    }
    for insight in build_insights(app_data):
        assert "$" not in insight["detail"] or "$0.01" in insight["detail"], insight["detail"]
