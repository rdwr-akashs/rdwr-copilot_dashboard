"""Tests for html_generation.generate_html() producing valid, fully-substituted HTML."""
from __future__ import annotations

import json
import re

from html_generation import generate_html


def _minimal_app_data():
    return {
        "generatedAt": "2026-01-01 00:00:00",
        "summary": {"totalCost": 1.23},
        "sessions": [],
        "analysis": {},
        "periods": {"default": "monthly", "labels": {}, "allTime": {}, "monthly": {}},
        "cli": {
            "available": False,
            "sessions": [],
            "byModel": [],
            "files": [],
            "tools": [],
            "otelAvailable": False,
            "otelPaths": [],
            "summary": {},
        },
    }


def test_generate_html_starts_with_doctype():
    html = generate_html(_minimal_app_data())
    assert html.startswith("<!DOCTYPE html")


def test_generate_html_has_no_unreplaced_placeholders():
    html = generate_html(_minimal_app_data())
    assert "__APP_JSON__" not in html
    assert "__PRICING_JSON__" not in html


def test_generate_html_embeds_app_data_json():
    app_data = _minimal_app_data()
    html = generate_html(app_data)
    # The web/ bundling pipeline (esbuild) may declare this with `var`/`let`/
    # `const` depending on the build's transpilation target, so match any of
    # them rather than pinning to one keyword.
    match = re.search(r"(?:const|var|let)\s+APP_DATA\s*=\s*(\{.*?\});\s*\n", html, re.DOTALL)
    assert match is not None, "APP_DATA assignment not found in generated HTML"
    embedded = json.loads(match.group(1))
    assert embedded["generatedAt"] == app_data["generatedAt"]
    assert embedded["summary"]["totalCost"] == 1.23


def test_generate_html_has_no_leftover_double_braces():
    # The dashboard's CSS/JS lives in the web/ source tree (bundled via
    # esbuild into web/dist/bundle.{css,js}), assembled by generate_html()
    # via simple marker/placeholder string replacement. A reintroduced
    # escaping bug in that assembly (or a stray literal `{{`/`}}` from an
    # older Python-string-escaping approach) would leak into the final
    # document. The embedded APP_DATA/PRICING_TABLE JSON blobs legitimately
    # contain `}}`-like sequences (e.g. two adjacent empty objects), so strip
    # those two assignments out before checking the rest of the document.
    html = generate_html(_minimal_app_data())
    stripped = re.sub(r"(?:const|var|let)\s+APP_DATA\s*=\s*\{.*?\};\n", "", html, flags=re.DOTALL)
    stripped = re.sub(r"(?:const|var|let)\s+PRICING_TABLE\s*=\s*\{.*?\};\n", "", stripped, flags=re.DOTALL)
    assert "{{" not in stripped
    assert "}}" not in stripped


def test_generate_html_is_valid_looking_document():
    html = generate_html(_minimal_app_data())
    assert html.rstrip().endswith("</html>")
    assert "<style>" in html
    assert "<script>" in html or "function renderApp" in html
