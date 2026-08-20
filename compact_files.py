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
from token_usage import new_token_block

DEFAULT_CACHE_VERIFY_SECONDS = max(30, env_int("COPILOT_DASHBOARD_CACHE_VERIFY_SECONDS", 300))
COMPRESSED_CACHE_WORKERS = max(1, (os.cpu_count() or 1) // 2)
_JSON_COMPRESSION_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
  max_workers=COMPRESSED_CACHE_WORKERS,
  thread_name_prefix="copilot-cache-zstd",
)


def truncate_for_dashboard(text: Any, limit: int, label: str = "text") -> str:
  value = "" if text is None else str(text)
  if len(value) <= limit:
    return value
  hidden = len(value) - limit
  return value[:limit].rstrip() + f"\n\n… [truncated {hidden:,} more characters from {label} to keep the dashboard responsive]"


def compact_sequence(items: list[Any], max_items: int, placeholder: Any, keep_head: int = 1) -> list[Any]:
  if len(items) <= max_items:
    return list(items)

  keep_head = max(0, min(keep_head, max_items - 1))
  keep_tail = max(0, max_items - keep_head - 1)
  omitted = len(items) - keep_head - keep_tail
  if omitted <= 0:
    return list(items[:max_items])

  compacted = list(items[:keep_head])
  compacted.append(placeholder)
  if keep_tail:
    compacted.extend(items[-keep_tail:])
  return compacted


def omitted_message(count: int) -> dict[str, Any]:
  return {
    "role": "meta",
    "parts": [
      {
        "type": "text",
        "label": "Omitted messages",
        "text": f"{count} additional messages omitted to keep the dashboard responsive.",
      }
    ],
  }


def omitted_part(count: int) -> dict[str, Any]:
  return {
    "type": "text",
    "label": "Omitted parts",
    "text": f"{count} additional parts omitted to keep the dashboard responsive.",
  }


def compact_message_part_for_ui(part: dict[str, Any]) -> dict[str, Any]:
  compacted = {
    "type": part.get("type", "text"),
    "label": part.get("label") or str(part.get("type", "text")).replace("_", " ").title(),
  }
  if part.get("tool_name"):
    compacted["tool_name"] = part.get("tool_name")
  if part.get("tool_id"):
    compacted["tool_id"] = part.get("tool_id")

  if compacted["type"] == "tool_call":
    compacted["arguments_pretty"] = truncate_for_dashboard(
      part.get("arguments_pretty") or part.get("text") or "",
      MAX_UI_MESSAGE_TEXT_CHARS,
      "tool call arguments",
    )
    compacted["text"] = compacted["arguments_pretty"]
  else:
    compacted["text"] = truncate_for_dashboard(
      part.get("text") or "",
      MAX_UI_MESSAGE_TEXT_CHARS,
      f"{compacted['type']} part",
    )

  return compacted


def compact_message_list_for_ui(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
  source_messages = list(messages or [])
  selected_messages = compact_sequence(
    source_messages,
    MAX_UI_MESSAGES_PER_EVENT,
    omitted_message(max(0, len(source_messages) - MAX_UI_MESSAGES_PER_EVENT + 1)),
    keep_head=1,
  )

  compacted_messages: list[dict[str, Any]] = []
  for message in selected_messages:
    if message.get("role") == "meta":
      compacted_messages.append(message)
      continue

    source_parts = list(message.get("parts", []))
    parts = compact_sequence(
      source_parts,
      MAX_UI_PARTS_PER_MESSAGE,
      omitted_part(max(0, len(source_parts) - MAX_UI_PARTS_PER_MESSAGE + 1)),
      keep_head=1,
    )
    compacted_messages.append(
      {
        "role": message.get("role", "unknown"),
        "parts": [compact_message_part_for_ui(part) for part in parts],
      }
    )

  return compacted_messages


def compact_event_for_ui(event: dict[str, Any]) -> dict[str, Any]:
  kind = event.get("kind")
  if kind == "user_message":
    return {
      "id": event.get("id"),
      "kind": kind,
      "title": event.get("title"),
      "source": event.get("source"),
      "ts": event.get("ts"),
      "duration_ms": event.get("duration_ms", 0.0),
      "content": truncate_for_dashboard(event.get("content", ""), MAX_UI_TEXT_CHARS, "user message"),
      "estimated_tokens": event.get("estimated_tokens", new_token_block()),
    }

  if kind == "tool":
    return {
      "id": event.get("id"),
      "kind": kind,
      "name": event.get("name"),
      "title": event.get("title"),
      "source": event.get("source"),
      "ts": event.get("ts"),
      "duration_ms": event.get("duration_ms", 0.0),
      "status": event.get("status", "unknown"),
      "mode": event.get("mode", "other"),
      "files": event.get("files", []),
      "args_pretty": truncate_for_dashboard(event.get("args_pretty", ""), MAX_UI_TEXT_CHARS, "tool input"),
      "result_text": truncate_for_dashboard(event.get("result_text", ""), MAX_UI_TEXT_CHARS, "tool output"),
      "estimated_tokens": event.get("estimated_tokens", new_token_block()),
    }

  return {
    "id": event.get("id"),
    "kind": kind,
    "title": event.get("title"),
    "model": event.get("model"),
    "segment_index": event.get("segment_index", 1),
    "is_segment_start": event.get("is_segment_start", False),
    "boundary_reasons": event.get("boundary_reasons", []),
    "source": event.get("source"),
    "ts": event.get("ts"),
    "duration_ms": event.get("duration_ms", 0.0),
    "delta_tokens": event.get("delta_tokens", new_token_block()),
    "attribution_tokens": event.get("attribution_tokens", new_token_block()),
    "billed_tokens": event.get("billed_tokens", new_token_block()),
    "prompt_tokens": event.get("prompt_tokens", 0.0),
    "output_tokens": event.get("output_tokens", 0.0),
    "cached_tokens": event.get("cached_tokens", 0.0),
    "uncached_prompt_tokens": event.get("uncached_prompt_tokens", 0.0),
    "prompt_diff": event.get("prompt_diff", 0.0),
    "cached_diff": event.get("cached_diff", 0.0),
    "context_breakdown": event.get("context_breakdown"),
    "estimated_tokens": event.get("estimated_tokens", new_token_block()),
    "carry_forward_tokens": event.get("carry_forward_tokens", new_token_block()),
    "ttft_ms": event.get("ttft_ms", 0.0),
    "debug_name": event.get("debug_name", ""),
    "response_id": event.get("response_id", ""),
    "max_tokens": event.get("max_tokens"),
    "request_options": truncate_for_dashboard(event.get("request_options", ""), MAX_UI_TEXT_CHARS, "request options"),
    "request_shape": truncate_for_dashboard(event.get("request_shape", ""), MAX_UI_TEXT_CHARS, "request shape"),
    "system_prompt_id": event.get("system_prompt_id"),
    "tools_id": event.get("tools_id"),
    "input_messages": compact_message_list_for_ui(event.get("input_messages", [])),
    "new_messages": compact_message_list_for_ui(event.get("new_messages", [])),
    "diff_mode": event.get("diff_mode", "append"),
    "response_messages": compact_message_list_for_ui(event.get("response_messages", [])),
    "response_text": truncate_for_dashboard(event.get("response_text", ""), MAX_UI_TEXT_CHARS, "assistant output"),
    "reasoning": truncate_for_dashboard(event.get("reasoning", ""), MAX_UI_TEXT_CHARS, "reasoning"),
    "tool_calls_emitted": [
      {
        "name": tool.get("name") or "tool",
        "arguments": truncate_for_dashboard(tool.get("arguments", ""), MAX_UI_MESSAGE_TEXT_CHARS, "emitted tool call arguments"),
      }
      for tool in event.get("tool_calls_emitted", [])
    ],
  }


def compact_session_for_ui(session: dict[str, Any]) -> dict[str, Any]:
  # Sessions are already compact (no events) by the time they reach the HTML
  # layer; events are loaded on demand via the full-session API.
  return {
    "id": session.get("id"),
    "session_id": session.get("session_id"),
    "session_key": session.get("session_key"),
    "source_ip": session.get("source_ip"),
    "title": session.get("title"),
    "timestamp": session.get("timestamp"),
    "model": session.get("model"),
    "model_names": session.get("model_names", []),
    "totals": session.get("totals", new_token_block()),
    "billed_totals": session.get("billed_totals", new_token_block()),
    "chat_count": session.get("chat_count", 0),
    "tool_count": session.get("tool_count", 0),
    "segment_count": session.get("segment_count", 0),
    "boundary_counts": session.get("boundary_counts", {}),
    "peak_prompt_tokens": session.get("peak_prompt_tokens", 0.0),
    "cache_hit_rate": session.get("cache_hit_rate", 0.0),
    "duration_ms": session.get("duration_ms", 0.0),
    "overhead": session.get("overhead", {}),
    "has_full": True,
  }


def compact_app_data_for_html(app_data: dict[str, Any]) -> dict[str, Any]:
  return {
    "generatedAt": app_data.get("generatedAt"),
    "summary": app_data.get("summary", {}),
    "sessions": [compact_session_for_ui(session) for session in app_data.get("sessions", [])],
    "analysis": app_data.get("analysis", {}),
    "periods": app_data.get("periods", {}),
  }
