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

READ_TOOLS = {"read_file"}
EDIT_TOOLS = {
    "apply_patch",
    "replace_string_in_file",
    "multi_replace_string_in_file",
    "create_file",
    "delete_file",
    "vscode_renameSymbol",
}

SKIP_FLATTEN_KEYS = {
    "$mid",
    "anchor",
    "options",
    "references",
    "priority",
    "lineBreakBefore",
    "ctor",
    "ctorName",
}

def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


MAX_UI_TEXT_CHARS = env_int("COPILOT_DASHBOARD_MAX_UI_TEXT_CHARS", 4000)
MAX_UI_MESSAGE_TEXT_CHARS = env_int("COPILOT_DASHBOARD_MAX_UI_MESSAGE_TEXT_CHARS", 1200)
MAX_UI_MESSAGES_PER_EVENT = max(3, env_int("COPILOT_DASHBOARD_MAX_UI_MESSAGES_PER_EVENT", 8))
MAX_UI_PARTS_PER_MESSAGE = max(2, env_int("COPILOT_DASHBOARD_MAX_UI_PARTS_PER_MESSAGE", 8))
MAX_UI_ASSET_TEXT_CHARS = env_int("COPILOT_DASHBOARD_MAX_UI_ASSET_TEXT_CHARS", 8000)
# Schema 7: compact entries keep session summary plus dense, mergeable analysis
# totals only. Full chat events/assets remain in the on-demand full cache.
CACHE_SCHEMA_VERSION = 7
DEFAULT_CACHE_VERIFY_SECONDS = max(30, env_int("COPILOT_DASHBOARD_CACHE_VERIFY_SECONDS", 300))
COMPRESSED_CACHE_WORKERS = max(1, (os.cpu_count() or 1) // 2)
_JSON_COMPRESSION_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
  max_workers=COMPRESSED_CACHE_WORKERS,
  thread_name_prefix="copilot-cache-zstd",
)

def parse_json_maybe(raw: Any, default: Any = None) -> Any:
    if raw is None:
        return default
    if not isinstance(raw, str):
        return raw
    text = raw.strip()
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:
        return default if default is not None else raw

def flatten_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts = [flatten_text(item) for item in value]
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict):
        parts: list[str] = []
        for key in ("text", "content", "markdown"):
            text = value.get(key)
            if isinstance(text, str) and text:
                parts.append(text)
        for key in ("response", "children", "node", "parts", "messages", "value"):
            if key in value:
                nested = flatten_text(value[key])
                if nested:
                    parts.append(nested)
        if not parts:
            for key, nested_value in value.items():
                if key in SKIP_FLATTEN_KEYS:
                    continue
                nested = flatten_text(nested_value)
                if nested:
                    parts.append(nested)
        return "\n".join(part for part in parts if part)
    return str(value)

def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 4))

def safe_json(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        parsed = parse_json_maybe(value, None)
        if parsed is not None and parsed is not value:
            return safe_json(parsed)
        return value
    try:
        return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(value)

def shorten(text: str, limit: int = 160) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"

def first_words(text: str, word_count: int = 10) -> str:
    words = [word for word in re.split(r"\s+", (text or "").strip()) if word]
    if not words:
        return ""
    return " ".join(words[:word_count])

def signed_diff(current: float | int, previous: float | int | None) -> float:
    if previous is None:
        return float(current or 0)
    return float(current or 0) - float(previous or 0)

def positive_diff(current: float | int, previous: float | int | None) -> float:
    return max(0.0, signed_diff(current, previous))

def unique_in_order(values: list[str]) -> list[str]:
  seen: set[str] = set()
  ordered: list[str] = []
  for value in values:
    if not value or value in seen:
      continue
    seen.add(value)
    ordered.append(value)
  return ordered

def detect_segment_boundaries(
  model_name: str,
  previous_model_name: str | None,
  input_tokens: float,
  previous_input_tokens: float | None,
  cached_tokens: float,
  previous_cached_tokens: float | None,
  diff_mode: str,
  previous_messages: list[dict[str, Any]],
) -> list[str]:
  """Detect true context/billing attribution boundaries between LLM calls.

  Important: `diff_mode == "reset"` only means the captured message arrays are not
  a strict append-only prefix match. In Copilot/OTel content capture that can happen
  because message serialization, tool-call wrappers, truncation, or injected context
  changed shape. It is therefore *not* reliable evidence of a real compaction.

  A real context reset/compaction should show up as a material drop in the observed
  input token counter. Cache reset is kept as a diagnostic reason, but callers should
  not treat cache_reset alone as a fresh full-prompt attribution boundary.
  """
  if previous_input_tokens is None:
    return []

  reasons: list[str] = []
  if previous_model_name and previous_model_name != model_name:
    reasons.append("model_switch")

  previous_input = float(previous_input_tokens or 0.0)
  current_input = float(input_tokens or 0.0)
  prompt_drop = previous_input - current_input

  # Only a substantial prompt-token drop is strong evidence that context was
  # compacted/reset. Do NOT use diff_mode == "reset" here; that caused ordinary
  # turns to be counted as full new segments and inflated input/cached totals.
  significant_prompt_drop = prompt_drop > max(512.0, previous_input * 0.20)
  if previous_messages and significant_prompt_drop:
    reasons.append("context_reset")

  previous_cached = float(previous_cached_tokens or 0.0)
  current_cached = float(cached_tokens or 0.0)
  if previous_cached > 0 and current_cached <= previous_cached * 0.10:
    reasons.append("cache_reset")

  return unique_in_order(reasons)
