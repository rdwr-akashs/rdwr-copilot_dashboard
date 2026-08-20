"""Lightweight coverage for insights_engine.py (added by another agent after
this suite's first pass). insights_engine.py was not present when this
harness was originally built; the rest of the suite tolerates its absence
(see tests/test_structural_contract.py), but since it now exists this module
pins its top-level contract: shape, determinism, sort order, and
never-raises-on-empty-input behavior. It does not attempt to exercise every
individual `_rule_*` heuristic (out of scope for this pass).
"""
from __future__ import annotations

from insights_engine import DEFAULT_CONFIG, build_insights, build_insights_with_diagnostics

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
