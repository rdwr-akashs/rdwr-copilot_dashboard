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

import diagnostics
from dashboard_utils import *
from token_usage import *
from compact_files import *
from model_pricing import *
from analysis_buckets import *
from json_storage import *
from json_storage import _JSON_COMPRESSION_EXECUTOR, _existing_json_path, _write_compressed_json_payload
from per_chat_calculations import *
from global_calculations import *
from compact_cache import *

def split_session_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split a freshly parsed session payload into (compact_payload, full_payload)."""
    session = payload.get("session") or {}
    asset_store = payload.get("assets", {}) if isinstance(payload.get("assets"), dict) else {}
    contribution = compute_session_contribution(session, asset_store)
    compact_payload = {
      "session": build_compact_session(session),
      "contribution": contribution,
      "telemetryFields": payload.get("telemetryFields", []),
      "entryTypes": payload.get("entryTypes", {}),
    }
    full_payload = {
      "session": session,
      "assets": asset_store,
    }
    return compact_payload, full_payload


def merge_session_payload(
    payload: dict[str, Any],
    sessions: list[dict[str, Any]],
    seen_session_ids: set[str],
    telemetry_fields: set[str],
    entry_types: collections.Counter,
    contributions_by_id: dict[str, dict[str, Any]],
) -> bool:
    session = payload.get("session")
    if not isinstance(session, dict):
      return False

    session_id = str(session.get("id") or session.get("session_key") or "")
    if not session_id or session_id in seen_session_ids:
      return False

    sessions.append(session)
    seen_session_ids.add(session_id)

    contribution = payload.get("contribution")
    if isinstance(contribution, dict):
      contributions_by_id[session_id] = contribution

    telemetry = payload.get("telemetryFields", [])
    if isinstance(telemetry, list):
      telemetry_fields.update(str(field) for field in telemetry if field)

    raw_entry_types = payload.get("entryTypes", {})
    if isinstance(raw_entry_types, dict):
      for key, value in raw_entry_types.items():
        try:
          entry_types[str(key)] += int(value)
        except (TypeError, ValueError):
          continue

    return True


class SessionCacheStore:
    # Class-level cache for foreign entries (loaded once, shared across instances)
    _foreign_entries_cache: dict[str, list[dict[str, Any]]] = {}
    _entry_mem_cache: dict[str, dict[str, Any]] = {}

    def __init__(self, root_dir: str | None = None, shared_foreign_entries: list[dict[str, Any]] | None = None):
      preferred_root = os.path.abspath(root_dir or default_dashboard_cache_root())
      self.root_dir = preferred_root
      self.shard_name = local_cache_shard_name()
      self.local_shard_dir = os.path.join(self.root_dir, self.shard_name)
      # Schema 2 layout: small compact entries + on-demand full payloads.
      self.local_compact_dir = os.path.join(self.local_shard_dir, "compact")
      self.local_full_dir = os.path.join(self.local_shard_dir, "full")
      self._shared_foreign_entries = shared_foreign_entries
      try:
        os.makedirs(self.local_compact_dir, exist_ok=True)
        os.makedirs(self.local_full_dir, exist_ok=True)
      except OSError:
        fallback_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".dashboard-cache")
        self.root_dir = fallback_root
        self.local_shard_dir = os.path.join(self.root_dir, self.shard_name)
        self.local_compact_dir = os.path.join(self.local_shard_dir, "compact")
        self.local_full_dir = os.path.join(self.local_shard_dir, "full")
        os.makedirs(self.local_compact_dir, exist_ok=True)
        os.makedirs(self.local_full_dir, exist_ok=True)

    def _entry_path(self, cache_key: str, shard_dir: str | None = None) -> str:
      base = shard_dir or self.local_shard_dir
      return os.path.join(base, "compact", f"{cache_key}.json")

    def _legacy_entry_path(self, cache_key: str, shard_dir: str | None = None) -> str:
      base = shard_dir or self.local_shard_dir
      return os.path.join(base, "compact", f"{cache_key}.json")

    def _full_path(self, cache_key: str, shard_dir: str | None = None) -> str:
      base = shard_dir or self.local_shard_dir
      return os.path.join(base, "full", f"{cache_key}.json.zst")

    def _legacy_full_path(self, cache_key: str, shard_dir: str | None = None) -> str:
      base = shard_dir or self.local_shard_dir
      return os.path.join(base, "full", f"{cache_key}.json")

    def _resolve_existing_entry_path(self, cache_key: str, shard_dir: str | None = None) -> str | None:
      return _existing_json_path(self._entry_path(cache_key, shard_dir))

    def _resolve_existing_full_path(self, cache_key: str, shard_dir: str | None = None) -> str | None:
      return _existing_json_path(self._full_path(cache_key, shard_dir))

    def read_local_entry(self, cache_key: str) -> dict[str, Any] | None:
      # Check in-memory cache first
      if cache_key in self._entry_mem_cache:
        return self._entry_mem_cache[cache_key]
      result = self._read_entry_path(self._entry_path(cache_key))
      if result:
        self._entry_mem_cache[cache_key] = result
      return result

    def _read_entry_path(self, path: str) -> dict[str, Any] | None:
      data = read_json_file(path)
      if not isinstance(data, dict):
        return None
      payload = data.get("payload")
      if not isinstance(payload, dict):
        return None
      return data

    def read_full_payload_at(self, path: str) -> dict[str, Any] | None:
      data = read_json_file(path)
      if not isinstance(data, dict):
        return None
      payload = data.get("payload")
      return payload if isinstance(payload, dict) else None

    def write_local_entry(self, cache_key: str, entry: dict[str, Any]) -> None:
      path = self._entry_path(cache_key)
      self._atomic_write_json(path, entry)

    def write_full_payload(self, cache_key: str, full_payload: dict[str, Any], session_id: str) -> str:
      path = self._full_path(cache_key)
      self._atomic_write_json(
        path,
        {
          "schemaVersion": CACHE_SCHEMA_VERSION,
          "cacheKey": cache_key,
          "sessionId": session_id,
          "payload": full_payload,
        },
      )
      return os.path.abspath(path)

    def _atomic_write_json(self, path: str, data: dict[str, Any]) -> None:
      if path.endswith(".zst"):
        _JSON_COMPRESSION_EXECUTOR.submit(_write_compressed_json_payload, path, data).result()
        return
      os.makedirs(os.path.dirname(path), exist_ok=True)
      tmp_path = f"{path}.tmp-{os.getpid()}-{int(time.time() * 1000)}"
      with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False)
      os.replace(tmp_path, path)

    def delete_local_entry(self, cache_key: str) -> None:
      for path in (
        self._entry_path(cache_key),
        self._legacy_entry_path(cache_key),
        self._full_path(cache_key),
        self._legacy_full_path(cache_key),
      ):
        try:
          os.remove(path)
        except OSError:
          continue

    def touch_local_verification(self, cache_key: str, entry: dict[str, Any], verified_at: float) -> None:
      updated = dict(entry)
      updated["verifiedAt"] = float(verified_at)
      self.write_local_entry(cache_key, updated)

    def iter_foreign_entries(self) -> list[dict[str, Any]]:
      # If shared foreign entries were provided, return them
      if self._shared_foreign_entries is not None:
        return self._shared_foreign_entries

      if not os.path.isdir(self.root_dir):
        return []

      # Check class-level cache first, but invalidate it when any foreign shard's
      # compact directory mtime changes. The dashboard writes cache files in
      # place, so this picks up new chats without requiring a server restart.
      shard_states: list[tuple[str, float]] = []
      for shard_dir in sorted(path for path in glob.glob(os.path.join(self.root_dir, "*")) if os.path.isdir(path)):
        if os.path.abspath(shard_dir) == os.path.abspath(self.local_shard_dir):
          continue
        compact_dir = os.path.join(shard_dir, "compact")
        if not os.path.isdir(compact_dir):
          continue
        try:
          shard_mtime = os.path.getmtime(compact_dir)
        except OSError:
          shard_mtime = 0.0
        shard_states.append((os.path.abspath(shard_dir), shard_mtime))

      cache_key = f"foreign_{self.root_dir}_{self.local_shard_dir}_{tuple(shard_states)}"
      if cache_key in self._foreign_entries_cache:
        return self._foreign_entries_cache[cache_key]

      entries_by_key: dict[str, dict[str, Any]] = {}
      for shard_dir, _shard_mtime in shard_states:
        compact_dir = os.path.join(shard_dir, "compact")
        candidate_paths = sorted(glob.glob(os.path.join(compact_dir, "*.json")))
        for path in candidate_paths:
          entry = self._read_entry_path(path)
          if not entry:
            continue
          # Make sure the full-payload pointer resolves on this machine (shared mount).
          if not entry.get("fullPath"):
            entry_cache_key = str(entry.get("cacheKey") or "")
            full_path = self._resolve_existing_full_path(entry_cache_key, shard_dir)
            entry["fullPath"] = os.path.abspath(full_path or self._full_path(entry_cache_key, shard_dir))
          entry_cache_key = str(entry.get("cacheKey") or os.path.basename(path).replace(".json", ""))
          entries_by_key[entry_cache_key] = entry

      # Cache the result
      entries = list(entries_by_key.values())
      stale_prefix = f"foreign_{self.root_dir}_{self.local_shard_dir}_"
      for existing_key in list(self._foreign_entries_cache.keys()):
        if existing_key.startswith(stale_prefix):
          del self._foreign_entries_cache[existing_key]
      self._foreign_entries_cache[cache_key] = entries
      return entries

    def find_full_payload_path_for_session(self, session_id: str) -> str | None:
      session_id = str(session_id or "").strip()
      if not session_id:
        return None

      candidate_ids = {session_id}
      if ":" in session_id:
        candidate_ids.add(session_id.split(":", 1)[1])

      if os.path.isdir(self.local_compact_dir):
        for cache_file in sorted(glob.glob(os.path.join(self.local_compact_dir, "*.json"))):
          entry = self._read_entry_path(cache_file)
          if not entry:
            continue
          entry_ids = {
            str(entry.get("sessionId") or "").strip(),
            str(entry.get("sessionKey") or "").strip(),
          }
          if candidate_ids.isdisjoint(entry_ids):
            continue

          full_path = str(entry.get("fullPath") or "")
          if not full_path:
            cache_key = str(entry.get("cacheKey") or os.path.basename(cache_file).replace(".json", ""))
            full_path = self._resolve_existing_full_path(cache_key) or self._full_path(cache_key)
          if full_path:
            return os.path.abspath(full_path)

      for entry in self.iter_foreign_entries():
        entry_ids = {
          str(entry.get("sessionId") or "").strip(),
          str(entry.get("sessionKey") or "").strip(),
        }
        if candidate_ids.isdisjoint(entry_ids):
          continue
        full_path = str(entry.get("fullPath") or "")
        if full_path:
          return os.path.abspath(full_path)

      return None


# Module-global index mapping session_id -> absolute full-payload cache path.
# Populated at the end of each build_dashboard_data() call so the HTTP server can
# serve full chat detail on demand without re-reading every cache file.
_FULL_SESSION_INDEX: dict[str, str] = {}
_FULL_SESSION_DIRS: dict[str, tuple[str, str]] = {}


def load_full_session_payload(session_id: str, cache_root_dir: str | None = None) -> dict[str, Any] | None:
  """Load the full session payload (events + assets) for one session on demand."""
  session_id = str(session_id or "")
  if not session_id:
    return None

  cache_store = SessionCacheStore(cache_root_dir)
  full_path = _FULL_SESSION_INDEX.get(session_id)
  if full_path and os.path.isfile(full_path):
    payload = cache_store.read_full_payload_at(full_path)
    if isinstance(payload, dict) and isinstance(payload.get("session"), dict):
      return payload

  # Prefer resolving the full payload path from the compact cache first.
  full_path = cache_store.find_full_payload_path_for_session(session_id)
  if full_path and os.path.isfile(full_path):
    payload = cache_store.read_full_payload_at(full_path)
    if isinstance(payload, dict) and isinstance(payload.get("session"), dict):
      _FULL_SESSION_INDEX[session_id] = full_path
      return payload

  # Fallback: re-parse from the raw log directory if the full cache file is gone.
  dirs = _FULL_SESSION_DIRS.get(session_id)
  if dirs:
    log_dir, session_dir = dirs
    if os.path.isdir(session_dir):
      parsed = parse_session_payload(session_dir)
      if parsed is not None:
        _compact, full_payload = split_session_payload(parsed)
        try:
          raw_session_id = str(parsed.get("session", {}).get("session_id") or os.path.basename(session_dir))
          cache_key = build_session_cache_key(log_dir, raw_session_id, session_dir)
          full_path = cache_store.write_full_payload(cache_key, full_payload, session_id)
          _FULL_SESSION_INDEX[session_id] = full_path
        except Exception as exc:
          # Only the re-cache failed; `full_payload` was parsed successfully and
          # is returned below, so this view is correct and no total moves. The
          # cost is that the next request re-parses the raw log instead of
          # hitting the cache - slow, not wrong.
          diagnostics.report(
            diagnostics.CODE_CACHE_UNREADABLE,
            f"Could not re-cache a session's full payload, so it will be re-parsed on every view: {exc}",
            severity="warning",
            impact="presentation",
            source=session_dir,
          )
        return full_payload
  return None


def _process_session_work_item(
    log_dir: str,
    session_dir: str,
    session_id: str,
    cache_root_dir: str | None,
    force_recalculate: bool,
    cache_verify_seconds: int,
    preloaded_cache: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, Any] | None, str, str, str] | None:
    """
    Worker function to process a single session.
    Returns (compact_payload, cache_key, log_dir, session_id) or None on failure.
    """
    cache_key = "<unknown>"
    try:
        cache_store = SessionCacheStore(cache_root_dir)

        cache_key = build_session_cache_key(log_dir, session_id, session_dir)
        # Use preloaded cache if available to avoid file I/O in worker threads.
        if preloaded_cache and cache_key in preloaded_cache:
          SessionCacheStore._entry_mem_cache[cache_key] = preloaded_cache[cache_key]

        compact_payload: dict[str, Any] | None = None
        quick_signature: str | None = None

        cached_entry = None if force_recalculate else (preloaded_cache or {}).get(cache_key)
        if cached_entry is None and not force_recalculate:
          cached_entry = cache_store.read_local_entry(cache_key)

        if cached_entry:
            schema_ok = int(cached_entry.get("schemaVersion", CACHE_SCHEMA_VERSION) or CACHE_SCHEMA_VERSION) == CACHE_SCHEMA_VERSION
            payload_obj = cached_entry.get("payload") if isinstance(cached_entry.get("payload"), dict) else None
            if schema_ok and payload_obj is not None:
                session_obj = payload_obj.get("session")
                if isinstance(session_obj, dict):
                    normalize_session_identity(session_obj, cache_store.shard_name)
                verified_at = float(cached_entry.get("verifiedAt") or cached_entry.get("generatedAt") or 0.0)
                # Fast path: trust recently verified compact entry and skip all raw-file scans.
                if (time.time() - verified_at) < cache_verify_seconds:
                    compact_payload = payload_obj
                else:
                    file_rows = iter_session_files_for_cache(session_dir)
                    quick_signature = compute_quick_file_signature(file_rows)
                    if cached_entry.get("quickSignature") == quick_signature:
                        # TEMPORARY: rely on quick signature only.
                        #
                        # If we ever need to re-enable the deeper content check, this is
                        # the place to compare:
                        #   compute_content_file_signature(file_rows)
                        # against the stored contentSignature.
                        compact_payload = payload_obj
                        # Skip verification touch in worker thread to avoid expensive disk write

        if compact_payload is None:
          file_rows = iter_session_files_for_cache(session_dir)
          quick_signature = quick_signature or compute_quick_file_signature(file_rows)
          parsed = parse_session_payload(session_dir)
          if parsed is None:
            cache_store.delete_local_entry(cache_key)
            return None

          compact_payload, full_payload = split_session_payload(parsed)
          session_key = str(compact_payload.get("session", {}).get("id") or session_id)
          full_path = cache_store.write_full_payload(cache_key, full_payload, session_key)
          now_ts = time.time()
          cache_store.write_local_entry(
            cache_key,
            {
              "schemaVersion": CACHE_SCHEMA_VERSION,
              "cacheKey": cache_key,
              "sessionId": session_key,
              "sessionKey": session_key,
              "sourceSessionId": session_id,
              "sourceIp": compact_payload.get("session", {}).get("source_ip"),
              "sessionDir": os.path.abspath(session_dir),
              "logDir": os.path.abspath(log_dir),
              "quickSignature": quick_signature,
              # TEMPORARY: contentSignature is intentionally omitted.
              # Quick signature is the only freshness check for now.
              "generatedAt": now_ts,
              "verifiedAt": now_ts,
              "cacheShard": cache_store.shard_name,
              "fullPath": full_path,
              "payload": compact_payload,
            },
          )

        session_key = str(compact_payload.get("session", {}).get("id") or session_id)
        return (compact_payload, cache_key, log_dir, session_key)
    except Exception as exc:
        print(
          f"[copilot_dashboard] failed session processing for '{session_id}' in '{session_dir}' (cache_key={cache_key}): {exc}",
          file=sys.stderr,
        )
        # Returning None drops this session from the run entirely, so every
        # total is lower than the truth by whatever it contained. The stderr
        # line above is developer tracing on a stream nobody reading the
        # dashboard sees; this is the same fact where the numbers are read.
        diagnostics.report(
          diagnostics.CODE_LOG_PARSE_FAILED,
          f"A session could not be processed and is missing from every total: {exc}",
          severity="error",
          impact="cost",
          source=session_dir,
        )
        return None


