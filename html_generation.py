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
from model_pricing import PRICING

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


def generate_html(app_data: dict[str, Any]) -> str:
    app_json = json.dumps(compact_app_data_for_html(app_data), ensure_ascii=False).replace("</", "<\\/")
    pricing_json = json.dumps(PRICING, ensure_ascii=False).replace("</", "<\\/")

    skeleton = _INDEX_HTML_PATH.read_text(encoding="utf-8")
    css = _BUNDLE_CSS_PATH.read_text(encoding="utf-8")
    js = _BUNDLE_JS_PATH.read_text(encoding="utf-8")

    html = skeleton.replace(_STYLES_MARKER, css).replace(_SCRIPT_MARKER, js)
    html = html.replace("__PRICING_JSON__", pricing_json)
    return html.replace("__APP_JSON__", app_json)


