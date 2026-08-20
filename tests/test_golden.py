"""Golden-file regression test for the dashboard's data pipeline.

Builds `app_data` from the synthetic fixtures in `conftest.py`, renders it
with `generate_html()`, and checks it against two kinds of baseline:

  1. `tests/golden/app_data.json` -- a strict, byte-for-byte comparison of
     the *data* the dashboard is built from (pretty-printed, sorted keys,
     `generatedAt` pinned to a constant). This is the meaningful contract:
     it pins the actual numbers (costs, token counts, aggregations) that
     `build_dashboard_data()` / `build_cli_dashboard_data()` /
     `usage_model.build_unified()` / `premium_requests.build_budget()`
     produce, and a real arithmetic/data regression anywhere in that
     pipeline will change this file and fail the test.

  2. A *structural* contract on the rendered HTML from `generate_html()`
     (see `test_golden_html_structural_contract` below) -- doctype, no
     leftover injection markers/placeholders, no `{{`/`}}` escaping
     artifacts, and (most importantly) that the APP_DATA JSON blob embedded
     in the HTML round-trips back to exactly
     `compact_files.compact_app_data_for_html(app_data)`. This is what
     actually matters for "did generate_html() do its assembly job
     correctly" without being sensitive to what the front-end team is doing
     to CSS/JS class names, layout, or copy.

## Why there is no longer a raw full-HTML byte-hash golden

An earlier version of this test additionally stored a sha256 hash of the
full rendered HTML (`tests/golden/dashboard.sha256`) and asserted it never
changed. That made sense when it existed to prove a *specific, one-time*
refactor (extracting the CSS/JS out of `html_generation.py`'s inline
triple-quoted string into the `web/` esbuild source tree) didn't change
rendered output. That refactor has since landed, and three UI agents are now
*actively and legitimately* rewriting markup/behavior under `web/js/**` and
`web/styles/**` as ongoing feature work -- so a full-HTML hash would now
change on essentially every commit to this repo, for reasons that have
nothing to do with a data/arithmetic regression. Keeping it as a hard
assertion would either (a) be updated reflexively without real scrutiny
every time it failed, which defeats its purpose as a regression guard, or
(b) generate constant false-positive noise. Per the task's guidance to keep
"the stable part... asserted strictly while the volatile rendered-HTML hash
is either regenerated deliberately or relaxed", this test relaxes it: the
old `tests/golden/dashboard.sha256` file has been removed, and the
structural contract above replaces it as the thing that's actually asserted
about the HTML. `tests/test_web_assembly.py` and `tests/test_generate_html.py`
separately cover the web/-bundling assembly contract in more depth.

To regenerate `tests/golden/app_data.json` after an intentional data-shape
change, run:

    $env:COPILOT_DASHBOARD_UPDATE_GOLDEN = "1"
    python -m pytest tests/test_golden.py -q
    Remove-Item Env:COPILOT_DASHBOARD_UPDATE_GOLDEN

or, in one line:

    COPILOT_DASHBOARD_UPDATE_GOLDEN=1 pytest tests/test_golden.py
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from dashboard_core import build_dashboard_data
from cli_usage import build_cli_dashboard_data
from html_generation import generate_html
from compact_files import compact_app_data_for_html

GOLDEN_DIR = Path(__file__).parent / "golden"
APP_DATA_GOLDEN_PATH = GOLDEN_DIR / "app_data.json"
NORMALIZED_GENERATED_AT = "2026-01-01 00:00:00"


def _build_golden_app_data(fake_debug_logs, tmp_cache_dir, fake_cli_db, fake_otel_jsonl):
    app_data = build_dashboard_data(
        [fake_debug_logs],
        cache_root_dir=tmp_cache_dir,
        force_recalculate=True,
        workers=2,
    )
    app_data["cli"] = build_cli_dashboard_data(fake_cli_db, otel_log_paths=[fake_otel_jsonl])
    # Pin the only inherently non-deterministic fields so the baseline is
    # stable across machines/runs: the generated-at timestamp, each session's
    # on-disk directory (a randomized pytest tmp_path), and the CLI db path.
    app_data["generatedAt"] = NORMALIZED_GENERATED_AT
    for session in app_data.get("sessions", []):
        if isinstance(session, dict) and "dir" in session:
            session["dir"] = "<normalized-session-dir>"
    cli_block = app_data.get("cli")
    if isinstance(cli_block, dict) and "dbPath" in cli_block:
        cli_block["dbPath"] = "<normalized-cli-db-path>"
    if isinstance(cli_block, dict) and cli_block.get("otelPaths"):
        cli_block["otelPaths"] = ["<normalized-otel-path>" for _ in cli_block["otelPaths"]]
    return app_data


def test_golden_app_data_output(fake_debug_logs, tmp_cache_dir, fake_cli_db, fake_otel_jsonl):
    """Strict, meaningful golden: the actual data/arithmetic the dashboard is built from."""
    app_data = _build_golden_app_data(fake_debug_logs, tmp_cache_dir, fake_cli_db, fake_otel_jsonl)
    normalized_app_data_json = json.dumps(app_data, indent=2, sort_keys=True, ensure_ascii=False)

    if os.environ.get("COPILOT_DASHBOARD_UPDATE_GOLDEN"):
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        APP_DATA_GOLDEN_PATH.write_text(normalized_app_data_json + "\n", encoding="utf-8")
        return

    assert APP_DATA_GOLDEN_PATH.exists(), (
        "Golden app_data.json is missing. Regenerate with "
        "COPILOT_DASHBOARD_UPDATE_GOLDEN=1 pytest tests/test_golden.py"
    )
    expected_app_data_json = APP_DATA_GOLDEN_PATH.read_text(encoding="utf-8").rstrip("\n")
    assert normalized_app_data_json == expected_app_data_json, (
        "app_data shape/values changed. If this is expected, regenerate with "
        "COPILOT_DASHBOARD_UPDATE_GOLDEN=1 pytest tests/test_golden.py"
    )


def test_golden_html_structural_contract(fake_debug_logs, tmp_cache_dir, fake_cli_db, fake_otel_jsonl):
    """Structural, whitespace/markup-churn-tolerant contract on the rendered HTML.

    Does NOT hash the full document (see module docstring for why): instead
    checks the specific things `generate_html()` is actually responsible for
    getting right, using the *real* fixture-derived app_data (not a generic
    minimal one) so the embedded-JSON round-trip check is meaningful.
    """
    app_data = _build_golden_app_data(fake_debug_logs, tmp_cache_dir, fake_cli_db, fake_otel_jsonl)
    html = generate_html(app_data)

    assert html.startswith("<!DOCTYPE html")
    assert html.rstrip().endswith("</html>")

    # No leftover assembly markers/placeholders.
    assert "<!-- STYLES -->" not in html
    assert "<!-- SCRIPT -->" not in html
    assert "__APP_JSON__" not in html
    assert "__PRICING_JSON__" not in html

    # No leaked Python-string-escaping artifacts (the historical bug class
    # this golden was originally built to guard against), checked outside
    # the embedded JSON blobs (which legitimately contain `}}`-like
    # sequences from adjacent empty objects).
    stripped = re.sub(r"(?:const|var|let)\s+APP_DATA\s*=\s*\{.*?\};\n", "", html, flags=re.DOTALL)
    stripped = re.sub(r"(?:const|var|let)\s+PRICING_TABLE\s*=\s*\{.*?\};\n", "", stripped, flags=re.DOTALL)
    assert "{{" not in stripped
    assert "}}" not in stripped

    # The most important invariant: the embedded APP_DATA blob round-trips
    # back to exactly what `compact_app_data_for_html()` produces from this
    # app_data -- i.e. generate_html() faithfully serializes/embeds the
    # compacted data pipeline output, independent of whatever the
    # surrounding markup/CSS/JS looks like. (generate_html() embeds the
    # *compacted* app_data, not the raw dict -- see html_generation.py and
    # compact_files.compact_app_data_for_html(); test_structural_contract.py
    # separately pins which keys that compaction step preserves/defaults.)
    match = re.search(r"(?:const|var|let)\s+APP_DATA\s*=\s*(\{.*?\});\s*\n", html, re.DOTALL)
    assert match is not None, "APP_DATA assignment not found in generated HTML"
    embedded = json.loads(match.group(1))
    expected_compacted = compact_app_data_for_html(app_data)
    assert embedded == expected_compacted, (
        "embedded APP_DATA does not round-trip to compact_app_data_for_html(app_data)"
    )
