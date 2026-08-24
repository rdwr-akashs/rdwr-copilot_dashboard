from __future__ import annotations

import argparse
import collections
import concurrent.futures
import glob
import hashlib
import json
import math
import os
import re
import socket
import struct
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import fcntl  # type: ignore
except Exception:  # pragma: no cover - non-Linux platforms
    fcntl = None

from dashboard_utils import *
from compact_files import compact_app_data_for_html
from model_pricing import CACHE_WRITE_PRICING, LONG_CONTEXT_PRICING, PRICING, cache_write_rate

# ---------------------------------------------------------------------------
# web/ assembler
#
# The dashboard front-end lives in web/ (index.html skeleton + web/styles/*.css
# + web/js/*.js ES modules, bundled by web/build.js via esbuild). This module
# stays a *thin assembler*: it loads the prebuilt web/index.html skeleton and
# the prebuilt web/dist/{bundle.css,bundle.js} artifacts, inlines them, and
# substitutes the __APP_JSON__ / __PRICING_JSON__ placeholders. It never
# requires Node/npm at generate time -- the committed web/dist/ output is
# always used as-is. See web/README.md for the build pipeline.
# ---------------------------------------------------------------------------

_WEB_DIR = Path(__file__).resolve().parent / "web"
_INDEX_HTML_PATH = _WEB_DIR / "index.html"
_BUNDLE_CSS_PATH = _WEB_DIR / "dist" / "bundle.css"
_BUNDLE_JS_PATH = _WEB_DIR / "dist" / "bundle.js"

_STYLES_MARKER = "<!-- STYLES -->"
_SCRIPT_MARKER = "<!-- SCRIPT -->"


def pricing_table_for_ui() -> dict[str, dict[str, Any]]:
    """`PRICING` widened with the other two rates GitHub publishes per model.

    The front-end's `PRICING_TABLE` was `{input, cached, output}` only, which is
    all `calcModelCost()` needs, but it left the reference tab unable to show
    two rates that materially change a bill: the cache-WRITE rate (1.25x input
    for Anthropic models, and the reason a cache-heavy session costs more than
    an input-rate estimate suggests) and the long-context tier that doubles most
    rates above a per-model prompt threshold.

    Additive by design - `cacheWrite`/`longContext` are extra keys on the same
    rows, so every existing consumer that reads `input`/`cached`/`output` keeps
    working untouched. `cacheWrite` is 0.0 for models whose pricing row prints
    "Not applicable", which is the rate they are actually billed at, and
    `longContext` is absent for models with a single tier at any prompt size.
    """
    table: dict[str, dict[str, Any]] = {}
    for name, rates in PRICING.items():
        row = dict(rates)
        row["cacheWrite"] = CACHE_WRITE_PRICING.get(name, cache_write_rate(name))
        tier = LONG_CONTEXT_PRICING.get(name)
        if tier:
            row["longContext"] = dict(tier)
        table[name] = row
    return table


def generate_html(app_data: dict[str, Any]) -> str:
    app_json = json.dumps(compact_app_data_for_html(app_data), ensure_ascii=False).replace("</", "<\\/")
    pricing_json = json.dumps(pricing_table_for_ui(), ensure_ascii=False).replace("</", "<\\/")

    skeleton = _INDEX_HTML_PATH.read_text(encoding="utf-8")
    css = _BUNDLE_CSS_PATH.read_text(encoding="utf-8")
    js = _BUNDLE_JS_PATH.read_text(encoding="utf-8")

    html = skeleton.replace(_STYLES_MARKER, css).replace(_SCRIPT_MARKER, js)
    html = html.replace("__PRICING_JSON__", pricing_json)
    return html.replace("__APP_JSON__", app_json)


