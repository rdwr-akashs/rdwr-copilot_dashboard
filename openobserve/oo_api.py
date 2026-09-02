"""One HTTP helper for the OpenObserve admin scripts in this directory.

Credentials and location come from the same environment variables the dashboard's
own exporter reads (`openobserve_export.py`), so a shell configured for one is
configured for all of them:

    OPENOBSERVE_BASE_URL     default http://localhost:5080
    OPENOBSERVE_ORG          default "default"
    OPENOBSERVE_USER         required
    OPENOBSERVE_PASSWORD     required
    OPENOBSERVE_INSECURE_TLS 1/true/yes to accept a self-signed HTTPS endpoint

These scripts talk to the management API (dashboards, streams, search); the
ingestion path lives in `openobserve_export.py` and `chronicle_export.py`.
"""
from __future__ import annotations

import base64
import json
import os
import ssl
import urllib.error
import urllib.request
from typing import Any

DEFAULT_BASE_URL = "http://localhost:5080"
DEFAULT_ORG = "default"


def base_url() -> str:
    return (os.environ.get("OPENOBSERVE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")


def org() -> str:
    return os.environ.get("OPENOBSERVE_ORG") or DEFAULT_ORG


def insecure_tls() -> bool:
    return os.environ.get("OPENOBSERVE_INSECURE_TLS", "").lower() in {"1", "true", "yes"}


def auth_header() -> str:
    """Basic auth from the same pair the dashboard exporter uses.

    No default credentials on purpose: a wrong password answers 401 on every
    call, which is easier to read than a fallback that works on one machine.
    """
    user = os.environ.get("OPENOBSERVE_USER") or ""
    password = os.environ.get("OPENOBSERVE_PASSWORD") or ""
    if not user or not password:
        raise SystemExit(
          "Missing OpenObserve credentials. Set $OPENOBSERVE_USER and $OPENOBSERVE_PASSWORD."
        )
    return "Basic " + base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")


def ssl_context() -> ssl.SSLContext | None:
    return ssl._create_unverified_context() if insecure_tls() else None


def api(
  method: str,
  path: str,
  body: Any = None,
  timeout: float = 180.0,
) -> tuple[bool, Any]:
    """Call `/api/{org}{path}`. Returns (ok, decoded body or error string); never raises."""
    request = urllib.request.Request(
      f"{base_url()}/api/{org()}{path}",
      data=json.dumps(body).encode("utf-8") if body is not None else None,
      method=method,
      headers={"Content-Type": "application/json", "Authorization": auth_header()},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl_context()) as response:
            payload = response.read()
            return True, (json.loads(payload) if payload else {})
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", "replace")[:300]
        return False, f"HTTP {exc.code}: {body_text}"
    except Exception as exc:  # noqa: BLE001
        return False, repr(exc)[:300]


def search(sql: str, start_us: int, end_us: int, stream_type: str = "logs", size: int = 5):
    """Run one SQL query. Returns (ok, result or error string)."""
    body = {
      "query": {
        "sql": sql,
        "start_time": start_us,
        "end_time": end_us,
        "from": 0,
        "size": size,
      }
    }
    return api("POST", f"/_search?type={stream_type}", body, timeout=90.0)


def load_dashboard(path: str) -> tuple[dict, dict]:
    """Return (whole document, the v8 body that panels and tabs live in)."""
    with open(path, encoding="utf-8") as handle:
        document = json.load(handle)
    return document, document.get("v8", document)


def panels(dashboard: dict):
    """Yield (tab, panel) for every panel, in the order a reader sees them."""
    for tab in dashboard.get("tabs") or []:
        for panel in tab.get("panels") or []:
            yield tab, panel
