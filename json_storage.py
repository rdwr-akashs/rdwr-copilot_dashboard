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

COMPRESSED_CACHE_WORKERS = max(1, (os.cpu_count() or 1) // 2)
_JSON_COMPRESSION_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=COMPRESSED_CACHE_WORKERS,
    thread_name_prefix="copilot-cache-zstd",
)

def parse_content_wrapper_file(path: str) -> Any:
    data = read_json_file(path)
    if data is None:
        return None
    if isinstance(data, dict) and "content" in data:
        wrapped = data.get("content")
        return parse_json_maybe(wrapped, wrapped)
    return data


def _existing_json_path(path: str) -> str | None:
  if path.endswith(".zst"):
    candidates = [path, path[:-4]]
  else:
    candidates = [f"{path}.zst", path]
  for candidate in candidates:
    if candidate and os.path.isfile(candidate):
      return candidate
  return None


def read_json_text(path: str) -> str | None:
  # `resolved is None` means the file simply is not there, which is a normal
  # cache miss - deliberately NOT reported. Everything below it means the file
  # exists but could not be read, which silently drops real data.
  resolved = _existing_json_path(path)
  if resolved is None:
    return None
  if resolved.endswith(".zst"):
    try:
      completed = subprocess.run(
        ["zstd", "-q", "-d", "-c", resolved],
        check=True,
        capture_output=True,
      )
    except Exception as exc:
      diagnostics.report(
        diagnostics.CODE_CACHE_CORRUPT,
        f"Could not decompress a cached file, so its sessions are missing from the totals: {exc}",
        severity="error",
        impact="cost",
        source=resolved,
      )
      return None
    return completed.stdout.decode("utf-8", errors="ignore")
  try:
    with open(resolved, "r", encoding="utf-8", errors="ignore") as handle:
      return handle.read()
  except Exception as exc:
    diagnostics.report(
      diagnostics.CODE_CACHE_UNREADABLE,
      f"Could not read a cached file, so its sessions are missing from the totals: {exc}",
      severity="error",
      impact="cost",
      source=resolved,
    )
    return None


def read_json_file(path: str) -> Any:
  raw_bytes = _read_json_bytes(path)
  if raw_bytes is None:
    return None
  resolved = _existing_json_path(path)
  if resolved and resolved.endswith(".zst"):
    expected = _read_checksum_text(resolved)
    if expected is not None and hashlib.sha256(raw_bytes).hexdigest() != expected:
      # The bytes decompressed but do not match the checksum written beside
      # them. Treated as an error rather than a miss: a torn or tampered cache
      # entry is exactly the case that must never pass silently.
      diagnostics.report(
        diagnostics.CODE_CACHE_CHECKSUM_MISMATCH,
        "A cached file failed its SHA256 check and was discarded, so its "
        "sessions are missing from the totals.",
        severity="error",
        impact="cost",
        source=resolved,
      )
      return None
  try:
    return json.loads(raw_bytes.decode("utf-8", errors="strict"))
  except Exception as exc:
    diagnostics.report(
      diagnostics.CODE_CACHE_BAD_JSON,
      f"A cached file was not valid JSON, so its sessions are missing from the totals: {exc}",
      severity="error",
      impact="cost",
      source=resolved or path,
    )
    return None


def _checksum_path(path: str) -> str:
  return f"{path}.sha256"


def _legacy_json_path(path: str) -> str:
  return path[:-4] if path.endswith(".zst") else path


def _read_checksum_text(path: str) -> str | None:
  candidates = [_checksum_path(path)]
  legacy_path = _legacy_json_path(path)
  if legacy_path != path:
    candidates.append(_checksum_path(legacy_path))
  for candidate in candidates:
    if not os.path.isfile(candidate):
      continue
    try:
      with open(candidate, "r", encoding="utf-8", errors="ignore") as handle:
        text = handle.read().strip()
    except Exception as exc:
      # An unreadable sidecar leaves `expected` as None, which SKIPS
      # verification entirely - so a corrupt entry would pass unchecked. The
      # totals are not wrong because of this, but the guard that protects them
      # is quietly off, which is worth saying out loud.
      diagnostics.report(
        diagnostics.CODE_CACHE_UNREADABLE,
        f"Could not read a cache checksum file, so integrity checking was skipped for it: {exc}",
        severity="warning",
        impact="presentation",
        source=candidate,
      )
      continue
    if text:
      return text.split()[0]
  return None


def _read_json_bytes(path: str) -> bytes | None:
  resolved = _existing_json_path(path)
  if resolved is None:
    return None
  if resolved.endswith(".zst"):
    try:
      completed = subprocess.run(
        ["zstd", "-q", "-d", "-c", resolved],
        check=True,
        capture_output=True,
      )
    except Exception as exc:
      diagnostics.report(
        diagnostics.CODE_CACHE_CORRUPT,
        f"Could not decompress a cached file, so its sessions are missing from the totals: {exc}",
        severity="error",
        impact="cost",
        source=resolved,
      )
      return None
    return completed.stdout
  try:
    with open(resolved, "rb") as handle:
      return handle.read()
  except Exception as exc:
    diagnostics.report(
      diagnostics.CODE_CACHE_UNREADABLE,
      f"Could not read a cached file, so its sessions are missing from the totals: {exc}",
      severity="error",
      impact="cost",
      source=resolved,
    )
    return None


class _HashingTextWriter:
  def __init__(self, binary_stream: Any, digest: Any):
    self._binary_stream = binary_stream
    self._digest = digest

  def write(self, text: str) -> int:
    data = text.encode("utf-8")
    self._digest.update(data)
    self._binary_stream.write(data)
    return len(text)

  def flush(self) -> None:
    try:
      self._binary_stream.flush()
    except Exception:
      pass


def _write_text_atomic(path: str, text: str) -> None:
  os.makedirs(os.path.dirname(path), exist_ok=True)
  tmp_path = f"{path}.tmp-{os.getpid()}-{int(time.time() * 1000)}"
  with open(tmp_path, "w", encoding="utf-8") as handle:
    handle.write(text)
  os.replace(tmp_path, path)


def _remove_path_if_exists(path: str) -> None:
  try:
    os.remove(path)
  except OSError:
    pass


def _write_compressed_json_payload(path: str, data: dict[str, Any]) -> str:
  digest = hashlib.sha256()
  tmp_path = f"{path}.tmp-{os.getpid()}-{int(time.time() * 1000)}"
  proc: subprocess.Popen[bytes] | None = None
  try:
    with open(tmp_path, "wb") as compressed_handle:
      proc = subprocess.Popen(
        ["zstd", "-q", "-T1", "-22", "--ultra", "-c"],
        stdin=subprocess.PIPE,
        stdout=compressed_handle,
        stderr=subprocess.PIPE,
      )
      assert proc.stdin is not None
      writer = _HashingTextWriter(proc.stdin, digest)
      json.dump(data, writer, ensure_ascii=False)
      writer.flush()
      proc.stdin.close()
      stderr_text = ""
      if proc.stderr is not None:
        stderr_text = proc.stderr.read().decode("utf-8", errors="ignore")
      returncode = proc.wait()
      if returncode != 0:
        raise RuntimeError(f"zstd exited with code {returncode}: {stderr_text.strip()}")
    os.replace(tmp_path, path)
    _write_text_atomic(_checksum_path(path), f"{digest.hexdigest()}\n")
    legacy_path = _legacy_json_path(path)
    if legacy_path != path:
      _remove_path_if_exists(legacy_path)
      _remove_path_if_exists(_checksum_path(legacy_path))
    return path
  except Exception:
    _remove_path_if_exists(tmp_path)
    if proc is not None:
      try:
        if proc.stdin is not None and not proc.stdin.closed:
          proc.stdin.close()
      except Exception:
        pass
      try:
        proc.kill()
      except Exception:
        pass
    raise


def register_asset(asset_store: dict[str, dict[str, Any]], category: str, payload: Any) -> str | None:
    if payload is None:
        return None
    serialized = safe_json(payload)
    digest = hashlib.sha1(serialized.encode("utf-8", errors="ignore")).hexdigest()[:12]
    asset_id = f"{category}-{digest}"
    bucket = asset_store[category]
    if asset_id in bucket:
        return asset_id

    if category == "systemPrompts":
        plain_text = flatten_text(payload)
        bucket[asset_id] = {
            "id": asset_id,
            "kind": category,
            "parts": payload,
            "plain_text": plain_text,
            "token_estimate": estimate_tokens(plain_text),
        }
    else:
        tool_names = []
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict) and item.get("name"):
                    tool_names.append(item["name"])
        bucket[asset_id] = {
            "id": asset_id,
            "kind": category,
            "definitions": payload,
            "plain_text": serialized,
            "tool_names": tool_names,
            "token_estimate": estimate_tokens(serialized),
        }
    return asset_id

