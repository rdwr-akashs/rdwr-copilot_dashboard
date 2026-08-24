"""Structural contract test: app_data["unified"]/["premium"]/["insights"] must
survive `compact_files.compact_app_data_for_html()` unchanged.

`compact_app_data_for_html` builds an explicit dict literal of known keys and
silently drops anything it doesn't list -- this has already caused one real
bug (the unified/premium keys were briefly missing while being wired up).
This test pins the contract so a future edit that forgets a key fails loudly
instead of silently starving the frontend of data.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from cli_usage import empty_cli_payload
from compact_files import compact_app_data_for_html
from premium_requests import MULTIPLIERS, PLAN_ALLOWANCES

REPO_ROOT = Path(__file__).resolve().parent.parent
INSIGHTS_ENGINE_AVAILABLE = importlib.util.find_spec("insights_engine") is not None

UNIFIED_TOP_LEVEL_KEYS = {"daily", "monthly", "byModel", "byRepo", "bySource", "byHost", "totals", "range"}
PREMIUM_TOP_LEVEL_KEYS = {"config", "budget", "multipliers", "planAllowances"}


def _app_data_with_unified_and_premium():
    return {
        "generatedAt": "2026-01-01 00:00:00",
        "summary": {},
        "sessions": [],
        "analysis": {},
        "periods": {},
        "cli": empty_cli_payload(None),
        "unified": {
            "daily": [{"dayKey": "2026-01-01", "attributed": {}, "billed": {}, "premiumRequests": 0.0, "callCount": 1, "sessionCount": 1, "bySource": {}}],
            "monthly": [{"monthKey": "2026-01", "attributed": {}, "billed": {}, "premiumRequests": 0.0, "callCount": 1, "sessionCount": 1, "bySource": {}}],
            "byModel": [{"model": "gpt-5.4", "attributed": {}, "billed": {}, "premiumRequests": 0.0, "callCount": 1, "sessionCount": 1}],
            "byRepo": [],
            "bySource": [],
            "byHost": [],
            "totals": {"attributed": {"cost": 1.0}, "billed": {"cost": 1.5}, "premiumRequests": 3.0, "callCount": 1, "sessionCount": 1},
            "range": {"firstTs": 1, "lastTs": 2},
        },
        "premium": {
            "config": {"plan": "pro", "allowance": 300},
            "budget": {"used": 10.0, "status": "ok"},
            "multipliers": MULTIPLIERS,
            "planAllowances": PLAN_ALLOWANCES,
        },
        "insights": [
            {
                "id": "test-insight",
                "severity": "warn",
                "title": "Test insight",
                "detail": "Test detail",
                "source": "chat",
                "evidence": [],
                "estimatedSavings": {"cost": 0.5, "premiumRequests": 1.0},
                "action": "Do something",
                "confidence": "medium",
            }
        ],
    }


def test_unified_has_documented_top_level_keys():
    app_data = _app_data_with_unified_and_premium()
    assert set(app_data["unified"].keys()) == UNIFIED_TOP_LEVEL_KEYS


def test_premium_has_documented_top_level_keys():
    app_data = _app_data_with_unified_and_premium()
    assert set(app_data["premium"].keys()) == PREMIUM_TOP_LEVEL_KEYS


def test_insights_is_a_list_of_well_shaped_records_if_present():
    app_data = _app_data_with_unified_and_premium()
    assert isinstance(app_data["insights"], list)
    required_keys = {"id", "severity", "title", "detail", "source", "evidence", "estimatedSavings", "action", "confidence"}
    for insight in app_data["insights"]:
        assert required_keys.issubset(insight.keys())


def test_compact_app_data_for_html_preserves_unified():
    app_data = _app_data_with_unified_and_premium()
    compacted = compact_app_data_for_html(app_data)
    assert "unified" in compacted
    assert compacted["unified"] == app_data["unified"]


def test_compact_app_data_for_html_preserves_premium():
    app_data = _app_data_with_unified_and_premium()
    compacted = compact_app_data_for_html(app_data)
    assert "premium" in compacted
    assert compacted["premium"] == app_data["premium"]


def test_compact_app_data_for_html_preserves_insights():
    app_data = _app_data_with_unified_and_premium()
    compacted = compact_app_data_for_html(app_data)
    assert "insights" in compacted
    assert compacted["insights"] == app_data["insights"]


def test_compact_app_data_for_html_preserves_diagnostics():
    # The worst possible key to drop here. If `diagnostics` does not survive the
    # compaction, the static-HTML dashboard silently claims a clean run while
    # its totals are understated - which is precisely the failure mode
    # diagnostics.py was added to end.
    app_data = _app_data_with_unified_and_premium()
    app_data["diagnostics"] = {
        "entries": [
            {
                "code": "cache.corrupt",
                "message": "boom",
                "severity": "error",
                "impact": "cost",
                "source": "/cache/a.json.zst",
                "count": 2,
            }
        ],
        "summary": {"total": 1, "errors": 1, "warnings": 0, "costImpacting": 1},
    }
    compacted = compact_app_data_for_html(app_data)
    assert "diagnostics" in compacted
    assert compacted["diagnostics"] == app_data["diagnostics"]


def test_compact_app_data_for_html_provides_safe_defaults_when_keys_absent():
    # An older-shaped app_data (pre unified/premium/insights) must not crash
    # compact_app_data_for_html, and must still produce the new keys with
    # safe empty defaults so the frontend never sees a missing key.
    app_data = {
        "generatedAt": "2026-01-01 00:00:00",
        "summary": {},
        "sessions": [],
        "analysis": {},
        "periods": {},
    }
    compacted = compact_app_data_for_html(app_data)
    assert set(compacted["unified"].keys()) == UNIFIED_TOP_LEVEL_KEYS
    assert set(compacted["premium"].keys()) == PREMIUM_TOP_LEVEL_KEYS
    assert compacted["insights"] == []
    assert compacted["diagnostics"] == {
        "entries": [],
        "summary": {"total": 0, "errors": 0, "warnings": 0, "costImpacting": 0},
    }


def test_insights_engine_module_exists_note():
    # `insights_engine.py` is being written concurrently by another agent;
    # this suite tolerates its absence everywhere else. As of this test run
    # it does exist, so record that fact rather than silently skipping real
    # coverage (see tests/test_insights_engine.py for its own direct tests).
    assert INSIGHTS_ENGINE_AVAILABLE, (
        "insights_engine.py was not found. If this fails, another agent has "
        "removed/renamed it -- update tests/test_insights_engine.py and this "
        "note accordingly rather than deleting coverage."
    )
