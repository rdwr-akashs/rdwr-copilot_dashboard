from __future__ import annotations

import argparse
import collections
import concurrent.futures
import getpass
import glob
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import socket
import struct
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import fcntl  # type: ignore
except Exception:  # pragma: no cover - non-Linux platforms
    fcntl = None

from dashboard_utils import *
from token_usage import *
from model_pricing import *
from compact_files import *
from analysis_buckets import *
from json_storage import *
from per_chat_calculations import *
from global_calculations import *
from compact_cache import *
from full_cache import *
from full_cache import _FULL_SESSION_DIRS, _FULL_SESSION_INDEX, _process_session_work_item
from html_generation import generate_html
from cli_usage import build_cli_dashboard_data, default_cli_db_path, default_cli_otel_paths, empty_cli_payload
from usage_model import records_from_chat_sessions, records_from_cli, build_unified
from premium_requests import load_config as load_premium_config, build_budget, get_multiplier, MULTIPLIERS, PLAN_ALLOWANCES
from insights_engine import build_insights_with_diagnostics

def discover_log_dirs() -> list[str]:
    if os.environ.get("COPILOT_DEBUG_LOGS"):
        return [os.environ["COPILOT_DEBUG_LOGS"]]

    home = os.path.expanduser("~")
    candidates = glob.glob(os.path.join(home, ".vscode-server/data/User/workspaceStorage/*/GitHub.copilot-chat/debug-logs"))
    candidates += glob.glob(os.path.join(home, ".vscode/data/User/workspaceStorage/*/GitHub.copilot-chat/debug-logs"))

    # Windows desktop VS Code storage locations.
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates += glob.glob(os.path.join(appdata, "Code/User/workspaceStorage/*/GitHub.copilot-chat/debug-logs"))
        candidates += glob.glob(os.path.join(appdata, "Code - Insiders/User/workspaceStorage/*/GitHub.copilot-chat/debug-logs"))

    return sorted(set(candidates))



def default_output_path() -> str:
    """Resolve the default generated-dashboard path in a cross-platform way.

    Historically this was hardcoded to /tmp/dashboard.html, which silently wrote to
    C:\\tmp on Windows. Honour COPILOT_DASHBOARD_OUTPUT first, then fall back to the
    platform temp directory.
    """
    configured = os.environ.get("COPILOT_DASHBOARD_OUTPUT")
    if configured:
        return os.path.abspath(os.path.expanduser(configured))
    return os.path.join(tempfile.gettempdir(), "dashboard.html")


# ---------------------------------------------------------------------------
# Privacy: --anonymize / COPILOT_DASHBOARD_ANONYMIZE
# ---------------------------------------------------------------------------
# On a shared/team deployment, `session.source_ip` (the cache-shard name -
# see `compact_cache.normalize_session_identity`), the `shard:session_id`
# composite session id/key it builds, `unified.byHost`, and any absolute
# path under the generating user's home directory (CLI `cwd`, its
# `session-store.db` path, OTel export paths, chat tool-call file paths
# surfaced in insight evidence) can all identify a specific developer or
# machine. `anonymize_app_data()` replaces all of that with stable-per-host
# pseudonyms and a generic "~" home-path prefix, applied as a final pass over
# the fully-built `app_data` so it automatically covers every place an
# identifier can reach the JSON embedded in the HTML - including
# `app_data["insights"]` evidence - without each producer needing its own
# opt-out.

_ANONYMIZE_SALT_FILENAME = "anonymize_salt"


def _env_flag(name: str) -> bool:
    """Parse a boolean-ish environment variable (1/true/yes/on, case-insensitive)."""
    return str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def _anonymize_salt_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".copilot-dashboard", _ANONYMIZE_SALT_FILENAME)


def _load_or_create_anonymize_salt() -> bytes:
    """Load the local anonymization salt, generating and persisting one on first use.

    The salt lives only on the local disk (`~/.copilot-dashboard/anonymize_salt`,
    the same config-directory convention as `premium_requests.py`'s
    `~/.copilot-dashboard/premium.json`) - it is never embedded in the
    generated HTML, logged, or committed. Losing/rotating it simply changes
    the pseudonyms on the next run; it does not affect any other data.
    """
    path = _anonymize_salt_path()
    try:
        if os.path.isfile(path):
            with open(path, "rb") as handle:
                data = handle.read().strip()
            if data:
                return data
    except Exception:
        pass
    salt = secrets.token_bytes(32)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(salt)
    except Exception:
        # Best effort: if we can't persist it, still return a salt so this
        # run is anonymized (pseudonyms just won't be stable across runs).
        pass
    return salt


def _pseudonym_for(value: str, salt: bytes) -> str:
    """Short, stable, non-reversible pseudonym for a host/IP identifier."""
    digest = hmac.new(salt, value.encode("utf-8", errors="ignore"), hashlib.sha256).hexdigest()
    return f"dev-{digest[:4]}"


# Generic host labels that are never personally identifying and should never
# be pseudonymized (they'd just become noisier without protecting anyone).
_ANONYMIZE_HOST_EXEMPT = {"unknown-host", "cli-local"}


def _collect_host_identifiers(app_data: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for session in app_data.get("sessions", []) or []:
        value = str(session.get("source_ip") or "").strip()
        if value:
            ids.add(value)
    for row in (app_data.get("unified") or {}).get("byHost", []) or []:
        value = str(row.get("host") or "").strip()
        if value:
            ids.add(value)
    return {value for value in ids if value not in _ANONYMIZE_HOST_EXEMPT}


def _walk_replace_strings(obj: Any, replacements: list[tuple[str, str]]) -> Any:
    if isinstance(obj, dict):
        return {key: _walk_replace_strings(value, replacements) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_walk_replace_strings(item, replacements) for item in obj]
    if isinstance(obj, str):
        out = obj
        for old, new in replacements:
            if old:
                out = out.replace(old, new)
        return out
    return obj


def anonymize_app_data(app_data: dict[str, Any], anonymize_paths: bool = True) -> dict[str, Any]:
    """Replace host/IP identifiers (and, optionally, home-directory paths) in `app_data`.

    Host/IP pseudonymization: every distinct `source_ip` / `unified.byHost`
    value (excluding the generic `"unknown-host"` / `"cli-local"` labels) is
    replaced everywhere it appears - including inside the `shard:session_id`
    composite session id/key - with a short, stable-per-machine pseudonym
    like `dev-a3f1` (HMAC-SHA256 of the value with a local-only salt,
    truncated; not reversible without the salt file).

    Path anonymization (`anonymize_paths=True`, the default whenever
    `--anonymize` is set): the generating user's home directory (in both its
    native and forward-slash forms, since some paths in this codebase mix
    separators) is replaced with `"~"`, and the OS username is replaced with
    the literal string `"user"`, everywhere in the tree - this is what
    scrubs CLI `cwd`, `session-store.db`/OTel paths, and chat tool-call file
    paths surfaced in insight evidence.

    Aggregate numeric values (costs, tokens, premium requests, counts) are
    never touched - only string values change.
    """
    salt = _load_or_create_anonymize_salt()
    host_ids = _collect_host_identifiers(app_data)

    # Longest-first so a host id that happens to contain another string we
    # replace later (e.g. the OS username) is fully substituted before any
    # shorter/generic substring replacement runs.
    replacements: list[tuple[str, str]] = [
        (value, _pseudonym_for(value, salt)) for value in sorted(host_ids, key=len, reverse=True)
    ]

    if anonymize_paths:
        home = os.path.expanduser("~")
        for variant in sorted({home, home.replace("\\", "/")}, key=len, reverse=True):
            if variant and variant != os.sep:
                replacements.append((variant, "~"))
        username = os.environ.get("USERNAME") or os.environ.get("USER") or ""
        try:
            username = username or getpass.getuser()
        except Exception:
            pass
        if username:
            replacements.append((username, "user"))

    return _walk_replace_strings(app_data, replacements)


def build_dashboard_data(
    log_dirs: list[str],
    cache_root_dir: str | None = None,
    force_recalculate: bool = False,
    cache_verify_seconds: int = DEFAULT_CACHE_VERIFY_SECONDS,
    workers: int = 8,
) -> dict[str, Any]:
    cache_verify_seconds = max(30, int(cache_verify_seconds or DEFAULT_CACHE_VERIFY_SECONDS))
    cache_store = SessionCacheStore(cache_root_dir)

    telemetry_fields: set[str] = set()
    entry_types: collections.Counter = collections.Counter()
    sessions: list[dict[str, Any]] = []
    seen_session_ids: set[str] = set()
    contributions_by_id: dict[str, dict[str, Any]] = {}
    local_cache_keys: set[str] = set()
    full_index: dict[str, str] = {}
    full_dirs: dict[str, tuple[str, str]] = {}

    # Collect all work items (log_dir, session_dir, session_id) tuples
    work_items: list[tuple[str, str, str]] = []
    work_cache_keys: set[str] = set()
    seen_work_session_ids: set[str] = set()
    for log_dir in log_dirs:
      for session_dir in sorted(path for path in glob.glob(os.path.join(log_dir, "*")) if os.path.isdir(path)):
        session_id = os.path.basename(session_dir)
        if session_id in seen_work_session_ids:
          continue
        seen_work_session_ids.add(session_id)
        work_items.append((log_dir, session_dir, session_id))
        work_cache_keys.add(build_session_cache_key(log_dir, session_id, session_dir))

    # Pre-load small local compact entries in main thread (sequential, cheap).
    preloaded_cache: dict[str, dict[str, Any]] = {}
    if not force_recalculate and cache_store.local_compact_dir and os.path.isdir(cache_store.local_compact_dir):
      try:
        compact_files = sorted(glob.glob(os.path.join(cache_store.local_compact_dir, "*.json")))
        for cache_file in compact_files:
          cache_name = os.path.basename(cache_file)
          cache_key = cache_name[:-5]
          try:
            entry = read_json_file(cache_file)
            if isinstance(entry, dict) and isinstance(entry.get("payload"), dict):
              preloaded_cache[cache_key] = entry
          except Exception:
            continue
      except Exception:
        pass

    # Pre-load foreign compact entries in main thread
    preloaded_foreign_entries: list[dict[str, Any]] = []
    if not force_recalculate:
      preloaded_foreign_entries = cache_store.iter_foreign_entries()

    # Process work items in parallel using ThreadPoolExecutor
    workers_clamped = max(1, min(64, int(workers or 8)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers_clamped) as executor:
      futures = [
        executor.submit(
          _process_session_work_item,
          log_dir,
          session_dir,
          session_id,
          cache_root_dir,
          force_recalculate,
          cache_verify_seconds,
          preloaded_cache,
        )
        for log_dir, session_dir, session_id in work_items
      ]

      results: list[tuple[dict[str, Any], str, str, str]] = []
      for future in concurrent.futures.as_completed(futures):
        result = future.result()
        if result is not None:
          results.append(result)

    # Map the source-aware session key -> (log_dir, session_dir) for on-demand full re-parse fallback.
    session_dirs_by_id: dict[str, tuple[str, str]] = {
      f"{cache_store.shard_name}:{session_id}": (log_dir, session_dir) for log_dir, session_dir, session_id in work_items
    }

    for payload, cache_key, log_dir, session_id in results:
      merged = merge_session_payload(
        payload,
        sessions=sessions,
        seen_session_ids=seen_session_ids,
        telemetry_fields=telemetry_fields,
        entry_types=entry_types,
        contributions_by_id=contributions_by_id,
      )
      if not merged:
        continue
      local_cache_keys.add(cache_key)
      full_index[session_id] = os.path.abspath(cache_store._resolve_existing_full_path(cache_key) or cache_store._full_path(cache_key))
      if session_id in session_dirs_by_id:
        full_dirs[session_id] = session_dirs_by_id[session_id]

    for cache_key, local_entry in preloaded_cache.items():
      if cache_key in work_cache_keys or cache_key in local_cache_keys:
        continue
      payload = local_entry.get("payload")
      if not isinstance(payload, dict):
        continue
      session_obj = payload.get("session")
      if isinstance(session_obj, dict):
        normalize_session_identity(session_obj, local_entry.get("cacheShard") or cache_store.shard_name)
      local_session_id = str(session_obj.get("id") or "") if isinstance(session_obj, dict) else ""
      merged = merge_session_payload(
        payload,
        sessions=sessions,
        seen_session_ids=seen_session_ids,
        telemetry_fields=telemetry_fields,
        entry_types=entry_types,
        contributions_by_id=contributions_by_id,
      )
      if merged and local_session_id:
        full_path = str(local_entry.get("fullPath") or "")
        if not full_path:
          full_path = cache_store._resolve_existing_full_path(cache_key) or cache_store._full_path(cache_key)
        full_index[local_session_id] = os.path.abspath(full_path)

    for foreign_entry in preloaded_foreign_entries:
      cache_key = str(foreign_entry.get("cacheKey") or "")
      if cache_key and cache_key in local_cache_keys:
        continue
      payload = foreign_entry.get("payload")
      if not isinstance(payload, dict):
        continue
      session_obj = payload.get("session")
      foreign_source_ip = str(foreign_entry.get("cacheShard") or "").strip()
      if isinstance(session_obj, dict) and session_obj:
        if foreign_source_ip and not session_obj.get("source_ip"):
          normalize_session_identity(session_obj, foreign_source_ip)
        elif not session_obj.get("session_key"):
          normalize_session_identity(session_obj, session_obj.get("source_ip") or foreign_source_ip)
      foreign_session_id = str(session_obj.get("id") or "") if isinstance(session_obj, dict) else ""
      merged = merge_session_payload(
        payload,
        sessions=sessions,
        seen_session_ids=seen_session_ids,
        telemetry_fields=telemetry_fields,
        entry_types=entry_types,
        contributions_by_id=contributions_by_id,
      )
      if merged and foreign_session_id and foreign_entry.get("fullPath"):
        full_index[foreign_session_id] = str(foreign_entry.get("fullPath"))

    sessions.sort(key=lambda session: session.get("timestamp") or 0, reverse=True)

    # Publish the full-session lookup index for the HTTP server (same process).
    _FULL_SESSION_INDEX.clear()
    _FULL_SESSION_INDEX.update(full_index)
    _FULL_SESSION_DIRS.clear()
    _FULL_SESSION_DIRS.update(full_dirs)

    monthly_trends = build_monthly_trends(sessions)
    monthly_trends_billed = build_monthly_trends(sessions, billed=True)
    all_time_bundle = build_period_bundle(
      sessions=sessions,
      asset_store={},
      telemetry_fields=telemetry_fields,
      entry_types=entry_types,
      monthly_trends=monthly_trends,
      monthly_trends_billed=monthly_trends_billed,
      contributions_by_id=contributions_by_id,
    )

    current_month_key = datetime.now().strftime("%Y-%m")
    current_month_sessions = [
      session for session in sessions
      if month_key_from_timestamp(session.get("timestamp")) == current_month_key
    ]
    monthly_bundle = build_period_bundle(
      sessions=current_month_sessions,
      asset_store={},
      telemetry_fields=telemetry_fields,
      entry_types=entry_types,
      monthly_trends=monthly_trends,
      monthly_trends_billed=monthly_trends_billed,
      contributions_by_id=contributions_by_id,
    )
    monthly_bundle["monthKey"] = current_month_key
    monthly_bundle["label"] = month_label(current_month_key)

    return {
      "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
      "summary": all_time_bundle["summary"],
      "sessions": sessions,
      "analysis": all_time_bundle["analysis"],
      "periods": {
        "default": "monthly",
        "labels": {
          "allTime": "All time",
          "monthly": month_label(current_month_key),
        },
        "allTime": all_time_bundle,
        "monthly": monthly_bundle,
      },
    }



def compose_app_data(
  log_dirs: list[str] | None = None,
  cache_root_dir: str | None = None,
  force_recalculate: bool = False,
  cache_verify_seconds: int = DEFAULT_CACHE_VERIFY_SECONDS,
  workers: int = 8,
  cli_db_path: str | None = None,
  cli_otel_log_paths: list[str] | None = None,
  premium_plan: str | None = None,
  premium_quota: int | None = None,
  premium_config_path: str | None = None,
  anonymize: bool = False,
) -> dict[str, Any]:
    """Build the complete ``app_data`` payload shared by every entry point.

    This is the single composition seam: both the batch generator
    (``write_dashboard``) and the live HTTP server call it, so neither can
    drift out of sync when a new stage is added here.
    """
    resolved_log_dirs = log_dirs or discover_log_dirs()
    if not resolved_log_dirs:
        raise RuntimeError("Could not find Copilot debug logs. Set COPILOT_DEBUG_LOGS or pass log directories explicitly.")

    app_data = build_dashboard_data(
      resolved_log_dirs,
      cache_root_dir=cache_root_dir,
      force_recalculate=force_recalculate,
      cache_verify_seconds=cache_verify_seconds,
      workers=workers,
    )
    try:
      app_data["cli"] = build_cli_dashboard_data(
        cli_db_path or default_cli_db_path(),
        otel_log_paths=cli_otel_log_paths if cli_otel_log_paths is not None else default_cli_otel_paths(),
      )
    except Exception:
      app_data["cli"] = empty_cli_payload(cli_db_path)

    # Unified backend usage model + premium-request/budget accounting. Purely
    # additive: failures degrade to empty structures rather than breaking the
    # rest of the dashboard, matching the app_data["cli"] pattern above.
    try:
      premium_config = load_premium_config(
        plan=premium_plan,
        allowance=premium_quota,
        config_path=premium_config_path,
      )
      multipliers = premium_config.get("multipliers")
      chat_records = records_from_chat_sessions(app_data.get("sessions"), multipliers=multipliers)
      cli_records = records_from_cli(app_data.get("cli"), multipliers=multipliers)
      unified = build_unified(chat_records + cli_records)
      budget = build_budget(unified, premium_config)
      app_data["unified"] = unified
      app_data["premium"] = {
        "config": premium_config,
        "budget": budget,
        "multipliers": MULTIPLIERS,
        "planAllowances": PLAN_ALLOWANCES,
      }

      # Attach premiumRequests onto existing per-session / per-model aggregates,
      # additively - no existing key's value is altered.
      try:
        premium_by_session: dict[str, float] = {}
        for record in chat_records:
          session_id = record.get("sessionId")
          if session_id:
            premium_by_session[session_id] = premium_by_session.get(session_id, 0.0) + float(record.get("premiumRequests", 0.0) or 0.0)
        for session in app_data.get("sessions", []) or []:
          session["premiumRequests"] = premium_by_session.get(session.get("id"), 0.0)

        # Legacy premium requests are charged per user PROMPT, not per model
        # call (see usage_model._premium_requests_for_prompts).
        #
        # A chat model row's `count` IS a prompt count (one logged chat request
        # per prompt), so those rows weight by their own count - which also
        # keeps the period-scoped bundles below period-correct. A CLI row's
        # `calls` counts model calls, which an agent loop inflates several-fold
        # over the prompts that drove them, so CLI rows weight by the prompt
        # counts apportioned per model in `cli_records` instead (same
        # whole-history scope as `cli.byModel`), falling back to the row's own
        # count only for a model the record pass never saw.
        cli_prompts_by_model: dict[str, float] = {}
        for record in cli_records:
          model_key = str(record.get("model") or "").lower()
          cli_prompts_by_model[model_key] = cli_prompts_by_model.get(model_key, 0.0) + float(record.get("promptCount", 0.0) or 0.0)

        def _attach_model_premium(
          model_rows: list[dict[str, Any]] | None,
          prompts_by_model: dict[str, float] | None = None,
        ) -> None:
          for row in model_rows or []:
            name = row.get("name") or row.get("model")
            count = float(row.get("count", row.get("calls", 0)) or 0)
            prompts = count if prompts_by_model is None else prompts_by_model.get(str(name or "").lower(), count)
            row["premiumRequests"] = prompts * get_multiplier(str(name or ""), multipliers)

        _attach_model_premium(app_data.get("analysis", {}).get("models"))
        for period_key in ("allTime", "monthly"):
          period_bundle = app_data.get("periods", {}).get(period_key) or {}
          _attach_model_premium((period_bundle.get("analysis") or {}).get("models"))
        _attach_model_premium(app_data.get("cli", {}).get("byModel"), cli_prompts_by_model)
      except Exception:
        pass
    except Exception:
      app_data["unified"] = {"daily": [], "monthly": [], "byModel": [], "byRepo": [], "bySource": [], "byHost": [], "totals": {}, "range": {"firstTs": None, "lastTs": None}}
      app_data["premium"] = {"config": {}, "budget": {}, "multipliers": MULTIPLIERS, "planAllowances": PLAN_ALLOWANCES}

    # Deterministic recommendations engine (insights_engine.py), built from
    # the unified/premium data above. Purely additive: a rule crash degrades
    # to an empty list plus a diagnostic, never the whole dashboard.
    try:
      insights, insight_errors = build_insights_with_diagnostics(app_data)
      app_data["insights"] = insights
      if insight_errors:
        app_data["_errors"] = (app_data.get("_errors") or []) + [f"insights_engine.{err}" for err in insight_errors]
    except Exception as exc:
      app_data["insights"] = []
      app_data["_errors"] = (app_data.get("_errors") or []) + [f"insights_engine: {exc!r}"]

    # Privacy: replace host/IP identifiers and home-directory paths with
    # stable pseudonyms when requested (--anonymize / COPILOT_DASHBOARD_ANONYMIZE).
    # Runs last, over the fully-built app_data, so it automatically covers
    # unified.byHost, session ids, CLI paths, and insight evidence alike.
    # `app_data["anonymized"]` tells the frontend whether it is looking at
    # real or pseudonymized identifiers, so it can label the dashboard honestly.
    effective_anonymize = anonymize or _env_flag("COPILOT_DASHBOARD_ANONYMIZE")
    if effective_anonymize:
      try:
        app_data.update(anonymize_app_data(app_data))
        app_data["anonymized"] = True
      except Exception as exc:
        app_data["anonymized"] = False
        app_data["_errors"] = (app_data.get("_errors") or []) + [f"anonymize: {exc!r}"]
    else:
      app_data["anonymized"] = False

    return app_data


def write_dashboard(
  output_file: str | None = None,
  log_dirs: list[str] | None = None,
  cache_root_dir: str | None = None,
  force_recalculate: bool = False,
  cache_verify_seconds: int = DEFAULT_CACHE_VERIFY_SECONDS,
  workers: int = 8,
  cli_db_path: str | None = None,
  cli_otel_log_paths: list[str] | None = None,
  premium_plan: str | None = None,
  premium_quota: int | None = None,
  premium_config_path: str | None = None,
  anonymize: bool = False,
) -> str:
    app_data = compose_app_data(
      log_dirs=log_dirs,
      cache_root_dir=cache_root_dir,
      force_recalculate=force_recalculate,
      cache_verify_seconds=cache_verify_seconds,
      workers=workers,
      cli_db_path=cli_db_path,
      cli_otel_log_paths=cli_otel_log_paths,
      premium_plan=premium_plan,
      premium_quota=premium_quota,
      premium_config_path=premium_config_path,
      anonymize=anonymize,
    )
    html = generate_html(app_data)
    output_path = os.path.abspath(os.path.expanduser(output_file)) if output_file else default_output_path()
    output_dir = os.path.dirname(output_path)
    if output_dir:
      os.makedirs(output_dir, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write(html)
    return output_path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate the Copilot token usage dashboard.")
    parser.add_argument("log_dirs", nargs="*", help="Optional debug-log directories to scan.")
    parser.add_argument("-o", "--output", help="Output HTML file path.")
    parser.add_argument(
      "--cache-dir",
      default=os.environ.get("COPILOT_DASHBOARD_CACHE_DIR") or default_dashboard_cache_root(),
      help="Directory for per-session parse cache (default: /mnt/radware/$USER/copilot_dashboard_cache when that mount exists, otherwise ~/.copilot-dashboard/cache).",
    )
    parser.add_argument(
      "--cache-verify-seconds",
      type=int,
      default=DEFAULT_CACHE_VERIFY_SECONDS,
      help="How often to content-verify unchanged sessions before trusting cached parse results.",
    )
    parser.add_argument(
      "--recalculate-all",
      action="store_true",
      help="Force full recalculation for all sessions even when cache entries are available.",
    )
    parser.add_argument(
      "--workers",
      type=int,
      default=8,
      help="Number of worker threads for parallel session processing (default: 8, max: 64).",
    )
    parser.add_argument(
      "--cli-db",
      default=os.environ.get("COPILOT_CLI_DB"),
      help="Path to the GitHub Copilot CLI session-store.db (default: ~/.copilot/session-store.db, if present).",
    )
    parser.add_argument(
      "--cli-otel-log",
      action="append",
      default=None,
      help=(
        "Path to a GitHub Copilot CLI OpenTelemetry JSONL export file (from COPILOT_OTEL_FILE_EXPORTER_PATH), "
        "used to enrich CLI sessions with real per-tool-call data. Repeatable. "
        "Default: $COPILOT_OTEL_FILE_EXPORTER_PATH, if present."
      ),
    )
    parser.add_argument(
      "--plan",
      default=None,
      help=(
        "GitHub Copilot plan used to resolve the monthly AI-credit allowance "
        "(free|pro|student|pro_plus|max|business|enterprise). Default: $COPILOT_PLAN, else 'pro'. "
        "This is a local estimate only, not official GitHub billing."
      ),
    )
    parser.add_argument(
      "--premium-quota",
      type=int,
      default=None,
      help=(
        "Explicit monthly AI-credit allowance (1 credit = $0.01 of model usage), "
        "overriding the --plan default. Default: $COPILOT_CREDIT_QUOTA (or legacy "
        "$COPILOT_PREMIUM_QUOTA), else the resolved plan's documented allowance."
      ),
    )
    parser.add_argument(
      "--premium-config",
      default=None,
      help=(
        "Path to a JSON config file overriding plan/credit-allowance/legacy-multipliers/thresholds. "
        "Default: $COPILOT_PREMIUM_CONFIG, else ~/.copilot-dashboard/premium.json, if present."
      ),
    )
    parser.add_argument(
      "--anonymize",
      action="store_true",
      default=False,
      help=(
        "Replace host/IP identifiers and home-directory paths in the generated dashboard with "
        "stable per-machine pseudonyms (e.g. 'dev-a3f1'), for sharing on a shared/team deployment "
        "without leaking colleagues' hostnames, IPs, or usernames. Aggregate numbers are unchanged. "
        "Default: $COPILOT_DASHBOARD_ANONYMIZE, else off."
      ),
    )
    args = parser.parse_args(argv)

    # Clamp workers between 1 and 64
    workers = max(1, min(64, int(args.workers or 8)))

    log_dirs = args.log_dirs or discover_log_dirs()
    for log_dir in log_dirs:
        print(f"Reading logs from: {log_dir}", file=sys.stderr)

    output_path = write_dashboard(
      output_file=args.output,
      log_dirs=log_dirs,
      cache_root_dir=args.cache_dir,
      force_recalculate=bool(args.recalculate_all),
      cache_verify_seconds=args.cache_verify_seconds,
      workers=workers,
      cli_db_path=args.cli_db,
      cli_otel_log_paths=args.cli_otel_log,
      premium_plan=args.plan,
      premium_quota=args.premium_quota,
      premium_config_path=args.premium_config,
      anonymize=bool(args.anonymize),
    )
    print(f"Dashboard written to: {output_path}", file=sys.stderr)
    print(output_path)


if __name__ == "__main__":
    main()
