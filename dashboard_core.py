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



def write_dashboard(
  output_file: str | None = None,
  log_dirs: list[str] | None = None,
  cache_root_dir: str | None = None,
  force_recalculate: bool = False,
  cache_verify_seconds: int = DEFAULT_CACHE_VERIFY_SECONDS,
  workers: int = 8,
) -> str:
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
    html = generate_html(app_data)
    output_path = os.path.abspath(os.path.expanduser(output_file)) if output_file else "/tmp/dashboard.html"
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
      help="Directory for per-session parse cache (default: /mnt/radware/$USER/copilot_dashboard_cache).",
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
    )
    print(f"Dashboard written to: {output_path}", file=sys.stderr)
    print(output_path)


if __name__ == "__main__":
    main()
