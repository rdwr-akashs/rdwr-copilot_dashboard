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
from compact_files import *
from per_chat_calculations import *
from global_calculations import *

DEFAULT_CACHE_VERIFY_SECONDS = max(30, env_int("COPILOT_DASHBOARD_CACHE_VERIFY_SECONDS", 300))

def default_dashboard_cache_root() -> str:
    configured = os.environ.get("COPILOT_DASHBOARD_CACHE_DIR")
    if configured:
      return os.path.abspath(configured)

    user = os.environ.get("USER") or os.path.basename(os.path.expanduser("~")) or "user"
    return os.path.join("/mnt/radware", user, "copilot_dashboard_cache")


def sanitize_cache_component(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(value or "")).strip("_")
    return cleaned or "unknown"


def _linux_ipv4_address_for_interface(interface_name: str) -> str | None:
    try:
      with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        ifname = interface_name[:15].encode("utf-8", errors="ignore")
        request = struct.pack("256s", ifname)
        response = fcntl.ioctl(sock.fileno(), 0x8915, request)
        return socket.inet_ntoa(response[20:24])
    except OSError:
      return None


def _preferred_cache_ip_from_interfaces() -> str | None:
    interface_names: list[str] = []
    try:
      interface_names = [name for _index, name in socket.if_nameindex()]
    except OSError:
      interface_names = []

    pattern = re.compile(r"^(?:ens|eth)\d+(?::\d+)?$")
    preferred_names = sorted(name for name in interface_names if pattern.match(name))

    for name in preferred_names:
      ip_address = _linux_ipv4_address_for_interface(name)
      if ip_address and ip_address.startswith("10."):
        return ip_address

    return None


def local_cache_shard_name() -> str:
    override = os.environ.get("COPILOT_DASHBOARD_CACHE_SHARD")
    if override:
      return sanitize_cache_component(override)

    ip_address = _preferred_cache_ip_from_interfaces()
    if ip_address:
      return sanitize_cache_component(ip_address)

    hostname = socket.gethostname()
    if hostname:
      return sanitize_cache_component(hostname)

    return "unknown-ip"


def normalize_session_identity(session: dict[str, Any], source_ip: str | None = None) -> dict[str, Any]:
    """Stamp a parsed session with a stable unique id and its source server IP."""
    source = sanitize_cache_component(source_ip or str(session.get("source_ip") or "") or local_cache_shard_name())
    original_id = str(session.get("session_id") or session.get("source_session_id") or session.get("id") or "").strip()
    if not original_id:
      original_id = "unknown-session"

    session["session_id"] = original_id
    session["source_session_id"] = original_id
    session["source_ip"] = source
    session["session_key"] = f"{source}:{original_id}" if source else original_id
    session["id"] = session["session_key"]
    return session


def build_session_cache_key(log_dir: str, session_id: str, session_dir: str) -> str:
    raw = f"{os.path.abspath(log_dir)}|{session_id}|{os.path.abspath(session_dir)}"
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:24]


def iter_session_files_for_cache(session_dir: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for root, _dirs, files in os.walk(session_dir):
      for filename in sorted(files):
        path = os.path.join(root, filename)
        if not os.path.isfile(path):
          continue
        try:
          st = os.stat(path)
        except OSError:
          continue
        rows.append(
          {
            "relative": os.path.relpath(path, session_dir),
            "path": path,
            "size": int(st.st_size),
            "mtime_ns": int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000))),
          }
        )
    rows.sort(key=lambda row: row["relative"])
    return rows


def compute_quick_file_signature(file_rows: list[dict[str, Any]]) -> str:
    digest = hashlib.sha1()
    for row in file_rows:
      digest.update(str(row.get("relative", "")).encode("utf-8", errors="ignore"))
      digest.update(b"\0")
      digest.update(str(row.get("size", 0)).encode("utf-8"))
      digest.update(b"\0")
      digest.update(str(row.get("mtime_ns", 0)).encode("utf-8"))
      digest.update(b"\0")
    return digest.hexdigest()


def compute_content_file_signature(file_rows: list[dict[str, Any]]) -> str:
    digest = hashlib.sha1()
    for row in file_rows:
      path = str(row.get("path") or "")
      digest.update(str(row.get("relative", "")).encode("utf-8", errors="ignore"))
      digest.update(b"\0")
      digest.update(str(row.get("size", 0)).encode("utf-8"))
      digest.update(b"\0")
      if not path:
        continue
      try:
        with open(path, "rb") as handle:
          while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
              break
            digest.update(chunk)
      except OSError:
        # If a file disappears mid-scan, quick signature will differ next cycle.
        continue
    return digest.hexdigest()


def new_parse_context() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    parse_analysis: dict[str, Any] = {
      "models": {},
      "tools": {},
      "files": {},
      "entry_types": collections.Counter(),
      "telemetry_fields": set(),
      "overhead": new_overhead_buckets(),
    }
    asset_store = {"systemPrompts": {}, "toolSets": {}}
    return parse_analysis, asset_store


def parse_session_payload(session_dir: str) -> dict[str, Any] | None:
    parse_analysis, asset_store = new_parse_context()
    session = parse_session(session_dir, parse_analysis, asset_store)
    if session is None:
      return None

    normalize_session_identity(session, local_cache_shard_name())

    return {
      "session": session,
      "telemetryFields": sorted(parse_analysis["telemetry_fields"]),
      "entryTypes": dict(parse_analysis["entry_types"]),
      "assets": asset_store,
    }


# Keys kept in the lightweight "compact" session embedded into the dashboard
# HTML and the chats list. Heavy per-call detail (events) is excluded and loaded
# on demand from the separate full-session cache file.
COMPACT_SESSION_KEYS = (
    "id",
    "session_id",
    "session_key",
    "source_ip",
    "title",
    "timestamp",
    "model",
    "model_names",
    "totals",
    "billed_totals",
    "overhead",
    "chat_count",
    "tool_count",
    "message_count",
    "segment_count",
    "boundary_counts",
    "peak_prompt_tokens",
    "cache_hit_rate",
    "duration_ms",
)


def build_compact_session(session: dict[str, Any]) -> dict[str, Any]:
    """Return a small summary of a session without the heavy per-event detail."""
    compact = {key: session.get(key) for key in COMPACT_SESSION_KEYS}
    compact["has_full"] = True
    return compact
