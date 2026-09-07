"""Tests for the Claude-insights half of openobserve/seed_schema.py.

Only the pieces this change added: the column plan must not drift from what
claude_insights_export.py actually writes (the same guarantee
test_chronicle_export.py's test_advice_columns_cover_every_field_chronicle_advice_writes
checks for chronicle), and every one of its non-regex-matched numeric columns must
seed as a number rather than the `schema_seed` marker string.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "openobserve") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "openobserve"))

import seed_schema  # noqa: E402
import claude_insights_export as cie  # noqa: E402


def test_claude_insights_columns_matches_the_exporter_exactly():
    plan = seed_schema.claude_insights_columns()
    assert set(plan) == {cie.STREAM}
    expected = (set(cie.META_COLUMNS) | set(cie.FACETS_COLUMNS)
               | set(cie.DERIVED_COLUMNS) | set(cie.ROW_IDENTITY))
    assert plan[cie.STREAM] == expected


def test_every_numeric_override_seeds_as_a_number_not_the_marker():
    for column in seed_schema.CLAUDE_INSIGHTS_NUMERIC_OVERRIDES:
        assert seed_schema.seed_value(column, cie.STREAM) == 0, column


def test_the_same_column_name_seeds_as_the_marker_outside_the_claude_stream():
    """The override is keyed by stream, the same care TYPES in the module docstring describes for
    duration_ms meaning something different in claude_code's events than in chronicle's usage rows.
    """
    assert seed_schema.seed_value("git_commits", "copilot_chronicle_sessions") == "schema_seed"


def test_bool_as_int_columns_are_covered_by_the_numeric_override():
    """If claude_insights_export ever adds a bool-as-int column without registering it here, its
    seed row types the column Utf8 and the first real 0/1 widens it back -- see TYPES."""
    assert set(cie.BOOL_AS_INT_COLUMNS) <= seed_schema.CLAUDE_INSIGHTS_NUMERIC_OVERRIDES


def test_streams_named_by_recognises_the_claude_insights_prefix(tmp_path):
    dashboard_path = tmp_path / "d.json"
    dashboard_path.write_text(
      '{"v8": {"tabs": [{"panels": [{"queries": [{"query": '
      '"SELECT 1 FROM claude_insights_sessions"}]}]}]}}',
      encoding="utf-8",
    )
    assert seed_schema.streams_named_by(str(dashboard_path)) == {"claude_insights_sessions"}
