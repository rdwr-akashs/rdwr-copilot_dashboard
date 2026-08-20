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
from analysis_buckets import *
from json_storage import *

def parse_message_parts(parts: Any) -> list[dict[str, Any]]:
    parsed_parts: list[dict[str, Any]] = []
    for index, part in enumerate(parts or []):
        if not isinstance(part, dict):
            text = flatten_text(part)
            parsed_parts.append({
                "index": index,
                "type": "text",
                "label": "Text",
                "text": text,
            })
            continue

        part_type = part.get("type", "unknown")
        record: dict[str, Any] = {
            "index": index,
            "type": part_type,
            "label": part_type.replace("_", " ").title(),
        }
        if part_type == "text":
            text = part.get("content") or part.get("text") or ""
            record["text"] = text
        elif part_type == "reasoning":
            text = part.get("content") or part.get("text") or flatten_text(part)
            record["text"] = text
            record["label"] = "Reasoning"
        elif part_type == "tool_call":
            arguments = part.get("arguments")
            record["tool_name"] = part.get("name") or "tool"
            record["tool_id"] = part.get("id")
            record["arguments"] = arguments
            record["arguments_pretty"] = safe_json(arguments)
            record["text"] = safe_json(arguments)
            record["label"] = f"Tool call · {record['tool_name']}"
        elif part_type in {"tool_call_response", "tool_result"}:
            response = part.get("response") or part.get("content") or part.get("result")
            text = flatten_text(response)
            record["tool_id"] = part.get("id")
            record["response"] = response
            record["text"] = text
            record["label"] = "Tool response"
        else:
            text = part.get("content") or part.get("text") or flatten_text(part)
            record["text"] = text
        parsed_parts.append(record)
    return parsed_parts


def parse_message_list(raw_messages: Any) -> list[dict[str, Any]]:
    messages = parse_json_maybe(raw_messages, raw_messages)
    if not isinstance(messages, list):
        return []

    parsed_messages: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            parsed_messages.append({
                "index": index,
                "role": "unknown",
                "parts": parse_message_parts([message]),
            })
            continue
        parsed_messages.append({
            "index": index,
            "role": message.get("role", "unknown"),
            "parts": parse_message_parts(message.get("parts", [])),
        })
    return parsed_messages


def message_list_to_text(messages: list[dict[str, Any]], include_tool_calls: bool = False, include_tool_responses: bool = True) -> str:
    chunks: list[str] = []
    for message in messages or []:
        role = message.get("role", "unknown")
        parts = message.get("parts", [])
        part_chunks: list[str] = []
        for part in parts:
            part_type = part.get("type")
            if part_type in {"text", "reasoning"}:
                if part.get("text"):
                    part_chunks.append(part["text"])
            elif part_type == "tool_call" and include_tool_calls:
                text = part.get("arguments_pretty") or part.get("text") or ""
                if text:
                    part_chunks.append(text)
            elif part_type in {"tool_call_response", "tool_result"} and include_tool_responses:
                if part.get("text"):
                    part_chunks.append(part["text"])
        if part_chunks:
            chunks.append(f"[{role}]\n" + "\n\n".join(part_chunks))
    return "\n\n".join(chunks)


def parse_tool_result_text(raw_result: Any) -> str:
    parsed = parse_json_maybe(raw_result, raw_result)
    if isinstance(parsed, str):
        maybe_json = parse_json_maybe(parsed, None)
        if maybe_json is not None and maybe_json is not parsed:
            parsed = maybe_json
    text = flatten_text(parsed)
    return text.strip() or (parsed if isinstance(parsed, str) else safe_json(parsed))


def iter_file_paths(obj: Any) -> list[str]:
    paths: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            key_lower = str(key).lower()
            if (
                key_lower in {"filepath", "path", "uri", "filename", "file", "targetfile", "targetpath"}
                and isinstance(value, str)
                and looks_like_file_path(value)
            ):
                paths.append(value)
            else:
                paths.extend(iter_file_paths(value))
    elif isinstance(obj, list):
        for item in obj:
            paths.extend(iter_file_paths(item))
    return paths


def looks_like_file_path(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    return (
        text.startswith("/")
        or text.startswith("file://")
        or bool(re.match(r"^[A-Za-z]:[\\/]", text))
        or bool(re.search(r"\.[A-Za-z0-9_+-]{1,12}$", text))
    )


def normalize_file_path(value: str) -> str:
    text = str(value or "").strip()
    if text.startswith("file://"):
        text = text[7:]
    return text


def extract_file_paths(tool_name: str, parsed_args: Any, raw_args: str) -> list[str]:
    paths = {normalize_file_path(path) for path in iter_file_paths(parsed_args)}

    if tool_name == "apply_patch":
        patch_text = ""
        if isinstance(parsed_args, dict):
            patch_text = parsed_args.get("input", "") or ""
        if not patch_text:
            patch_text = raw_args or ""
        for match in re.finditer(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", patch_text, re.MULTILINE):
            paths.add(normalize_file_path(match.group(1).strip()))

    if raw_args:
        for match in re.finditer(r"(?:file://)?(?:/[^\s\"'<>:,;]+|[A-Za-z]:[\\/][^\s\"'<>:,;]+)", raw_args):
            paths.add(normalize_file_path(match.group(0)))

    return sorted(path for path in paths if isinstance(path, str) and looks_like_file_path(path))


def tool_mode(tool_name: str) -> str:
    normalized = str(tool_name or "").lower()
    if tool_name in READ_TOOLS:
        return "read"
    if tool_name in EDIT_TOOLS:
        return "edit"
    if any(marker in normalized for marker in ("read", "grep", "search", "find", "list", "open", "fetch")):
        return "read"
    if any(marker in normalized for marker in ("edit", "write", "patch", "replace", "create", "delete", "rename", "insert")):
        return "edit"
    return "other"


def short_path(path: str) -> str:
    if not path:
        return ""
    home = os.path.expanduser("~")
    if path.startswith(home + os.sep):
        return "~" + path[len(home) :]
    return path


def diff_messages(previous: list[dict[str, Any]], current: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    prefix = 0
    upper = min(len(previous), len(current))
    while prefix < upper and previous[prefix] == current[prefix]:
        prefix += 1
    if prefix == len(previous):
        return current[prefix:], "append"
    if prefix == 0:
        return current, "reset"
    return current[prefix:], "splice"


def build_chat_title(model_name: str, reasoning: str) -> str:
    base = f"chat {model_name or 'unknown'}"
    reasoning = (reasoning or "").strip()
    if reasoning and reasoning != "[encrypted]":
        snippet = first_words(reasoning, 10)
        if snippet:
            return f"{base} — {snippet}"
    return base


def normalize_breakdown(buckets: dict[str, float], target_total: float) -> dict[str, float]:
    if target_total <= 0:
        return {key: 0.0 for key in buckets}

    working = {key: max(0.0, float(value)) for key, value in buckets.items()}
    total = sum(working.values())
    if total <= 0:
        normalized = {key: 0.0 for key in working}
        normalized["other"] = float(target_total)
        return normalized

    scaled = {key: value * (float(target_total) / total) for key, value in working.items()}
    assigned = sum(value for key, value in scaled.items() if key != "other")
    scaled["other"] = max(0.0, float(target_total) - assigned)
    return scaled


def file_ratio_for_tool_event(event: dict[str, Any] | None) -> float:
    if not event:
        return 0.0
    files = event.get("files") or event.get("file_event_refs") or []
    mode = str(event.get("mode") or "other").lower()
    if mode == "read":
        return 0.75
    if mode == "edit":
        return 0.65
    if not files:
        return 0.0
    return 0.50


def build_context_breakdown(
    input_messages: list[dict[str, Any]],
    system_prompt_asset: dict[str, Any] | None,
    tools_asset: dict[str, Any] | None,
    pending_tool_events: list[dict[str, Any]] | None,
    prompt_tokens: float,
    cached_tokens: float,
    max_context_window_tokens: float | None,
    reserved_response_tokens: float | None,
 ) -> dict[str, Any]:
    estimated = {
        "system_instructions": float((system_prompt_asset or {}).get("token_estimate", 0) or 0),
        "tool_definitions": float((tools_asset or {}).get("token_estimate", 0) or 0),
        "messages": 0.0,
        "tool_results": 0.0,
        "other": 0.0,
    }
    overhead_estimated = {
        "system_prompt": float((system_prompt_asset or {}).get("token_estimate", 0) or 0),
        "tool_definitions": float((tools_asset or {}).get("token_estimate", 0) or 0),
        "assistant_context": 0.0,
        "user_messages": 0.0,
        "tools": 0.0,
        "files": 0.0,
        "unattributed": 0.0,
    }
    tool_event_queue = collections.deque(pending_tool_events or [])
    tool_ratio_by_id: dict[str, float] = {}

    def inferred_event_from_tool_part(part: dict[str, Any]) -> dict[str, Any]:
        tool_name = str(part.get("tool_name") or "tool")
        raw_args = part.get("arguments_pretty") or part.get("text") or ""
        parsed_args = part.get("arguments")
        if parsed_args is None:
            parsed_args = parse_json_maybe(raw_args, raw_args)
        return {
            "mode": tool_mode(tool_name),
            "files": extract_file_paths(tool_name, parsed_args, str(raw_args or "")),
        }

    for message in input_messages:
        role = message.get("role", "unknown")
        for part in message.get("parts", []):
            part_type = part.get("type")
            text = part.get("text") or part.get("arguments_pretty") or ""
            token_estimate = float(estimate_tokens(text)) if text else 0.0
            if role == "user" and part_type in {"tool_call_response", "tool_result"}:
                estimated["tool_results"] += token_estimate
                event = tool_event_queue.popleft() if tool_event_queue else None
                tool_id = str(part.get("tool_id") or "")
                file_ratio = tool_ratio_by_id.get(tool_id, file_ratio_for_tool_event(event))
                overhead_estimated["files"] += token_estimate * file_ratio
                overhead_estimated["tools"] += token_estimate * (1.0 - file_ratio)
            elif role == "assistant" and part_type == "tool_call":
                estimated["other"] += token_estimate
                event = tool_event_queue[0] if tool_event_queue else inferred_event_from_tool_part(part)
                file_ratio = file_ratio_for_tool_event(event)
                tool_id = str(part.get("tool_id") or "")
                if tool_id:
                    tool_ratio_by_id[tool_id] = file_ratio
                overhead_estimated["files"] += token_estimate * file_ratio
                overhead_estimated["tools"] += token_estimate * (1.0 - file_ratio)
            elif part_type in {"text", "reasoning"} and role in {"user", "assistant", "system"}:
                estimated["messages"] += token_estimate
                if role == "user":
                    overhead_estimated["user_messages"] += token_estimate
                elif role == "assistant":
                    overhead_estimated["assistant_context"] += token_estimate
                elif role == "system":
                    overhead_estimated["system_prompt"] += token_estimate
            else:
                estimated["other"] += token_estimate
                overhead_estimated["unattributed"] += token_estimate

    normalized = normalize_breakdown(estimated, prompt_tokens)
    overhead_total = sum(max(0.0, float(value or 0.0)) for value in overhead_estimated.values())
    if prompt_tokens > 0 and overhead_total > 0:
        overhead_scale = float(prompt_tokens) / overhead_total
        overhead_normalized = {
            key: max(0.0, float(value or 0.0)) * overhead_scale
            for key, value in overhead_estimated.items()
        }
    else:
        overhead_normalized = {key: 0.0 for key in overhead_estimated}
        overhead_normalized["unattributed"] = float(prompt_tokens or 0.0)
    max_context = float(max_context_window_tokens or 0) or None
    categories = []
    labels = {
        "system_instructions": "System Instructions",
        "tool_definitions": "Tool Definitions",
        "messages": "Messages",
        "tool_results": "Tool Results",
        "other": "Other",
    }
    for key in ["system_instructions", "tool_definitions", "messages", "tool_results", "other"]:
        tokens = normalized.get(key, 0.0)
        categories.append({
            "key": key,
            "label": labels[key],
            "tokens": tokens,
            "percent_of_prompt": (tokens / prompt_tokens * 100.0) if prompt_tokens else 0.0,
            "percent_of_window": (tokens / max_context * 100.0) if max_context else 0.0,
        })

    reserved_tokens = float(reserved_response_tokens or 0.0)
    if max_context and reserved_tokens > max_context:
        reserved_tokens = max_context

    return {
        "prompt_tokens": float(prompt_tokens),
        "cached_tokens": float(cached_tokens),
        "uncached_tokens": max(0.0, float(prompt_tokens) - float(cached_tokens)),
        "max_context_window_tokens": max_context,
        "used_percent_of_window": (float(prompt_tokens) / max_context * 100.0) if max_context else 0.0,
        "reserved_response_tokens": reserved_tokens,
        "reserved_percent_of_window": (reserved_tokens / max_context * 100.0) if max_context else 0.0,
        "categories": categories,
        "overhead_estimate": overhead_normalized,
    }


def load_model_limits(session_dir: str) -> dict[str, dict[str, Any]]:
    models_path = os.path.join(session_dir, "models.json")
    data = read_json_file(models_path)
    limits_by_model: dict[str, dict[str, Any]] = {}
    if not isinstance(data, list):
        return limits_by_model

    for item in data:
        if not isinstance(item, dict):
            continue
        capabilities = item.get("capabilities") or {}
        limits = capabilities.get("limits") or {}
        names = [item.get("id"), item.get("name"), item.get("model_picker_name"), capabilities.get("family")]
        for name in names:
            if isinstance(name, str) and name:
                limits_by_model[name.lower()] = limits
    return limits_by_model


def parse_title(session_dir: str) -> str | None:
    title_files = glob.glob(os.path.join(session_dir, "title-*.jsonl"))
    for title_path in sorted(title_files):
        try:
            with open(title_path, "r", encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    entry = json.loads(line)
                    if entry.get("type") != "agent_response":
                        continue
                    response_messages = parse_message_list(entry.get("attrs", {}).get("response", []))
                    text_parts = [
                        part.get("text", "")
                        for message in response_messages
                        for part in message.get("parts", [])
                        if part.get("type") == "text" and part.get("text")
                    ]
                    text = "\n\n".join(text_parts)
                    if text.strip():
                        return text.strip()
        except Exception:
            continue
    return None


def register_tool_event_direct_stats(session_id: str, event: dict[str, Any], analysis: dict[str, Any]) -> None:
  bucket = ensure_tool_bucket(analysis, event["name"], event["mode"])
  bucket["count"] += 1
  bucket["duration_ms"] += event.get("duration_ms", 0.0)
  bucket["errors"] += 0 if event.get("status") == "ok" else 1
  bucket["payload_tokens_estimate"] += event.get("payload_tokens_estimate", 0.0)
  bucket["session_ids"].add(session_id)
  event["file_event_refs"] = []

  for file_path in event.get("files", []):
    file_bucket = ensure_file_bucket(analysis, file_path)
    file_bucket["session_ids"].add(session_id)
    file_bucket["tools"].add(event["name"])
    file_bucket["payload_tokens_estimate"] += event.get("payload_tokens_estimate", 0.0)
    file_bucket["tool_reference_count"] += 1
    if event["mode"] == "read":
      file_bucket["read_count"] += 1
    elif event["mode"] == "edit":
      file_bucket["edit_count"] += 1
    usage_key = f"{event['name']}::{event['mode']}"
    usage_bucket = file_bucket["tool_usage"].get(usage_key)
    if usage_bucket is None:
      usage_bucket = make_file_tool_usage_bucket(event["name"], event["mode"])
      file_bucket["tool_usage"][usage_key] = usage_bucket
    usage_bucket["count"] += 1
    usage_bucket["duration_ms"] += float(event.get("duration_ms", 0.0) or 0.0)
    usage_bucket["payload_tokens_estimate"] += float(event.get("payload_tokens_estimate", 0.0) or 0.0)
    add_token_block(usage_bucket, event.get("estimated_tokens", new_token_block()))
    usage_bucket["session_ids"].add(session_id)
    event["file_event_refs"].append({"path": file_path})


def allocate_delta_to_contributors(
    contributors: list[dict[str, Any]],
    delta_tokens: dict[str, float],
    analysis: dict[str, Any],
    session: dict[str, Any],
    record_overhead: bool = True,
) -> None:
  def add_overhead(kind: str, tokens: dict[str, float], scale: float = 1.0) -> None:
    if not record_overhead:
      return
    add_token_block(analysis["overhead"][kind], tokens, scale)
    add_token_block(session["overhead"][kind], tokens, scale)

  if not contributors:
    add_overhead("unattributed", delta_tokens)
    return

  total_weight = sum(max(1.0, float(contributor.get("weight", 0.0))) for contributor in contributors)
  if total_weight <= 0:
    total_weight = float(len(contributors))

  for contributor in contributors:
    weight = max(1.0, float(contributor.get("weight", 0.0)))
    share = weight / total_weight
    token_share = new_token_block()
    add_token_block(token_share, delta_tokens, share)

    event = contributor.get("event")
    if contributor.get("kind") == "assistant_context" and event is not None:
      add_token_block(event.setdefault("carry_forward_tokens", new_token_block()), token_share)
    elif event is not None:
      add_token_block(event.setdefault("estimated_tokens", new_token_block()), token_share)

    kind = contributor.get("kind")
    if kind == "tool":
      tool_name = contributor.get("tool_name") or "tool"
      bucket = ensure_tool_bucket(analysis, tool_name)
      add_token_block(bucket, token_share)

      file_ratio = 0.0
      contributor_file_paths = contributor.get("files") or []
      file_refs = (event or {}).get("file_event_refs") or []
      if file_refs or contributor_file_paths:
        mode = str((event or {}).get("mode") or "other").lower()
        if mode == "read":
          file_ratio = 0.75
        elif mode == "edit":
          file_ratio = 0.65
        else:
          file_ratio = 0.50

      tool_ratio = max(0.0, 1.0 - file_ratio)
      if tool_ratio:
        add_overhead("tools", token_share, tool_ratio)
      if file_ratio:
        add_overhead("files", token_share, file_ratio)

      if file_refs:
        per_file_share = 1.0 / len(file_refs)
        for ref in file_refs:
          file_path = ref.get("path")
          file_bucket = ensure_file_bucket(analysis, file_path)
          add_token_block(file_bucket, token_share, per_file_share)
      elif contributor_file_paths:
        per_file_share = 1.0 / len(contributor_file_paths)
        for file_path in contributor_file_paths:
          file_bucket = ensure_file_bucket(analysis, file_path)
          add_token_block(file_bucket, token_share, per_file_share)
    elif kind == "system_prompt":
      add_overhead("system_prompt", token_share)
    elif kind == "tool_response":
      add_overhead("tools", token_share)
    elif kind == "tool_definitions":
      add_overhead("tool_definitions", token_share)
    elif kind == "assistant_context":
      add_overhead("assistant_context", token_share)
    elif kind == "user_message":
      add_overhead("user_messages", token_share)
    else:
      add_overhead("unattributed", token_share)


def allocate_delta_to_context_breakdown(
    context_breakdown: dict[str, Any] | None,
    delta_tokens: dict[str, float],
    analysis: dict[str, Any],
    session: dict[str, Any],
) -> bool:
  overhead_estimate = (context_breakdown or {}).get("overhead_estimate")
  if not isinstance(overhead_estimate, dict):
    return False

  weights = {
    key: max(0.0, float(overhead_estimate.get(key, 0.0) or 0.0))
    for key in analysis.get("overhead", {})
  }
  total_weight = sum(weights.values())
  if total_weight <= 0:
    return False

  for key, weight in weights.items():
    if weight <= 0:
      continue
    token_share = new_token_block()
    add_token_block(token_share, delta_tokens, weight / total_weight)
    add_token_block(analysis["overhead"][key], token_share)
    add_token_block(session["overhead"][key], token_share)
  return True


def build_input_contributors(
    new_messages: list[dict[str, Any]],
    pending_user_events: list[dict[str, Any]],
    pending_tool_events: list[dict[str, Any]],
    previous_chat_event: dict[str, Any] | None,
    system_prompt_asset: dict[str, Any] | None,
    tools_asset: dict[str, Any] | None,
    system_prompt_changed: bool,
    tools_changed: bool,
) -> list[dict[str, Any]]:
    contributors: list[dict[str, Any]] = []

    if system_prompt_changed and system_prompt_asset:
        contributors.append({
            "kind": "system_prompt",
            "weight": max(1, system_prompt_asset.get("token_estimate", 0)),
            "title": "System prompt",
        })
    if tools_changed and tools_asset:
        contributors.append({
            "kind": "tool_definitions",
            "weight": max(1, tools_asset.get("token_estimate", 0)),
            "title": "Tool definitions",
        })

    user_queue = list(pending_user_events)
    tool_queue = list(pending_tool_events)
    pending_tool_contributors: collections.deque[dict[str, Any]] = collections.deque()
    assistant_texts: list[str] = []

    for message in new_messages:
        role = message.get("role", "unknown")
        user_texts: list[str] = []
        for part in message.get("parts", []):
            part_type = part.get("type")
            if role == "user" and part_type == "text" and part.get("text"):
                user_texts.append(part["text"])
            elif role == "assistant" and part_type in {"text", "reasoning"} and part.get("text"):
                assistant_texts.append(part["text"])
            elif role == "assistant" and part_type == "tool_call":
                matched_event = tool_queue.pop(0) if tool_queue else None
                contributor = {
                    "kind": "tool",
                    "event": matched_event,
                    "tool_name": part.get("tool_name") or (matched_event or {}).get("name") or "tool",
                    "files": (matched_event or {}).get("files") or [],
                    "weight": max(1, estimate_tokens(part.get("arguments_pretty", ""))),
                }
                contributors.append(contributor)
                pending_tool_contributors.append(contributor)
            elif role == "user" and part_type in {"tool_call_response", "tool_result"}:
                response_text = part.get("text") or ""
                if pending_tool_contributors:
                    pending_tool_contributors[0]["weight"] += estimate_tokens(response_text)
                    pending_tool_contributors.popleft()
                else:
                    contributors.append({
                    "kind": "tool_response",
                        "weight": max(1, estimate_tokens(response_text)),
                    "title": "Tool response",
                    })

        if user_texts:
            matched_event = user_queue.pop(0) if user_queue else None
            contributors.append({
                "kind": "user_message",
                "event": matched_event,
                "weight": max(1, estimate_tokens("\n".join(user_texts))),
                "title": "User message",
            })

    if assistant_texts:
        contributors.append({
            "kind": "assistant_context",
            "event": previous_chat_event,
            "weight": max(1, estimate_tokens("\n".join(assistant_texts))),
            "title": "Assistant context",
        })

    return [contributor for contributor in contributors if contributor.get("weight", 0) > 0]


def load_asset_from_reference(
    session_dir: str,
    filename: str | None,
    asset_store: dict[str, dict[str, Any]],
    asset_cache: dict[str, Any],
    category: str,
) -> tuple[str | None, dict[str, Any] | None]:
    if not filename:
        return None, None

    path = os.path.join(session_dir, filename)
    if path in asset_cache:
        asset_id = asset_cache[path]
        if asset_id is None:
            return None, None
        return asset_id, asset_store[category].get(asset_id)

    payload = parse_content_wrapper_file(path)
    asset_id = register_asset(asset_store, category, payload)
    asset_cache[path] = asset_id
    if asset_id is None:
        return None, None
    return asset_id, asset_store[category].get(asset_id)


def iter_log_streams(session_dir: str) -> list[tuple[str, str]]:
    streams = [("main", os.path.join(session_dir, "main.jsonl"))]
    for subagent_path in sorted(glob.glob(os.path.join(session_dir, "runSubagent-*.jsonl"))):
        name = os.path.basename(subagent_path).replace(".jsonl", "").replace("runSubagent-", "")
        name = name.split("-toolu_")[0]
        streams.append((f"subagent:{name}", subagent_path))
    return [(label, path) for label, path in streams if os.path.exists(path)]


def parse_session(session_dir: str, analysis: dict[str, Any], asset_store: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    session_id = os.path.basename(session_dir)
    model_limits = load_model_limits(session_dir)
    boundary_counts: collections.Counter[str] = collections.Counter()
    session = {
        "id": session_id,
        "dir": session_dir,
        "title": parse_title(session_dir),
        "timestamp": None,
        "model": None,
        "model_names": [],
        "events": [],
        "totals": new_token_block(),
        "billed_totals": new_token_block(),
        "overhead": new_overhead_buckets(),
        "chat_count": 0,
        "tool_count": 0,
        "message_count": 0,
        "source_labels": [],
        "segment_count": 0,
        "boundary_counts": {},
        "latest_prompt_tokens": 0.0,
        "latest_cached_tokens": 0.0,
        "latest_context_breakdown": None,
        "peak_prompt_tokens": 0.0,
        "peak_prompt_event_id": None,
    }
    asset_cache: dict[str, Any] = {}
    local_model_totals: dict[str, dict[str, float]] = collections.defaultdict(new_token_block)
    event_sequence = 0

    for source_label, log_path in iter_log_streams(session_dir):
        session["source_labels"].append(source_label)
        previous_messages: list[dict[str, Any]] = []
        previous_chat_event: dict[str, Any] | None = None
        pending_chat_event: dict[str, Any] | None = None
        pending_user_events: list[dict[str, Any]] = []
        pending_tool_events: list[dict[str, Any]] = []
        previous_system_prompt_id: str | None = None
        previous_tools_id: str | None = None
        previous_input_tokens: float | None = None
        previous_cached_tokens: float | None = None
        previous_model_name: str | None = None
        source_segment_index = 0

        try:
            with open(log_path, "r", encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    try:
                        entry = json.loads(line)
                    except Exception:
                        continue

                    entry_type = entry.get("type")
                    attrs = entry.get("attrs", {}) or {}
                    ts = entry.get("ts") or 0
                    duration_ms = float(entry.get("dur") or 0.0)
                    analysis["telemetry_fields"].update(attrs.keys())
                    analysis["entry_types"][entry_type] += 1

                    if session["timestamp"] is None and ts:
                        session["timestamp"] = ts

                    if entry_type == "user_message":
                        text = attrs.get("content", "") or ""
                        event = {
                            "id": f"{session_id}:{source_label}:event-{event_sequence}",
                            "kind": "user_message",
                            "title": shorten(text.splitlines()[0] if text else "User message", 120),
                            "source": source_label,
                            "ts": ts,
                            "order": event_sequence,
                            "duration_ms": duration_ms,
                            "content": text,
                            "estimated_tokens": new_token_block(),
                        }
                        event_sequence += 1
                        session["events"].append(event)
                        pending_user_events.append(event)
                        session["message_count"] += 1
                        continue

                    if entry_type == "tool_call":
                        raw_args = attrs.get("args", "") or ""
                        parsed_args = parse_json_maybe(raw_args, raw_args)
                        pretty_args = safe_json(parsed_args)
                        result_text = parse_tool_result_text(attrs.get("result", ""))
                        files = extract_file_paths(entry.get("name", "unknown"), parsed_args, raw_args)
                        mode = tool_mode(entry.get("name", "unknown"))
                        payload_tokens = estimate_tokens(pretty_args) + estimate_tokens(result_text)
                        event = {
                            "id": f"{session_id}:{source_label}:event-{event_sequence}",
                            "kind": "tool",
                            "name": entry.get("name", "unknown"),
                            "title": entry.get("name", "unknown"),
                            "source": source_label,
                            "ts": ts,
                            "order": event_sequence,
                            "duration_ms": duration_ms,
                            "status": entry.get("status", "unknown"),
                            "mode": mode,
                            "files": files,
                            "args_pretty": pretty_args,
                            "result_text": result_text,
                            "payload_tokens_estimate": payload_tokens,
                            "estimated_tokens": new_token_block(),
                        }
                        if files:
                            event["title"] = f"{event['name']} — {shorten(short_path(files[0]), 80)}"
                        event_sequence += 1
                        session["events"].append(event)
                        pending_tool_events.append(event)
                        session["tool_count"] += 1
                        register_tool_event_direct_stats(session_id, event, analysis)
                        continue

                    if entry_type == "llm_request":
                        model_name = attrs.get("model", "unknown") or "unknown"
                        input_tokens = float(attrs.get("inputTokens", 0) or 0)
                        output_tokens = float(attrs.get("outputTokens", 0) or 0)
                        cached_tokens = float(attrs.get("cachedTokens", 0) or 0)
                        input_messages = parse_message_list(attrs.get("inputMessages", []))
                        new_messages, diff_mode = diff_messages(previous_messages, input_messages)

                        system_prompt_id, system_prompt_asset = load_asset_from_reference(
                            session_dir,
                            attrs.get("systemPromptFile"),
                            asset_store,
                            asset_cache,
                            "systemPrompts",
                        )
                        tools_id, tools_asset = load_asset_from_reference(
                            session_dir,
                            attrs.get("toolsFile"),
                            asset_store,
                            asset_cache,
                            "toolSets",
                        )

                        system_prompt_changed = system_prompt_id != previous_system_prompt_id
                        tools_changed = tools_id != previous_tools_id

                        boundary_reasons = detect_segment_boundaries(
                          model_name=model_name,
                          previous_model_name=previous_model_name,
                          input_tokens=input_tokens,
                          previous_input_tokens=previous_input_tokens,
                          cached_tokens=cached_tokens,
                          previous_cached_tokens=previous_cached_tokens,
                          diff_mode=diff_mode,
                          previous_messages=previous_messages,
                        )
                        # Only true context resets/model switches should make this
                        # call receive full-prompt attribution. A cache_reset by itself
                        # is diagnostic only; treating it as a full segment boundary
                        # inflates cached/input totals.
                        full_prompt_boundary_reasons = {"context_reset", "model_switch"}
                        segment_start = (
                            previous_input_tokens is None
                            or any(reason in full_prompt_boundary_reasons for reason in boundary_reasons)
                        )
                        if segment_start:
                          source_segment_index += 1
                          session["segment_count"] += 1
                          # Note: source_segment_index is per-stream (resets each stream).
                          # session["segment_count"] accumulates across all streams.
                        if boundary_reasons:
                          for reason in boundary_reasons:
                            boundary_counts[reason] += 1
                          new_messages = input_messages
                          diff_mode = "reset"
                          if system_prompt_asset:
                            system_prompt_changed = True
                          if tools_asset:
                            tools_changed = True

                        billed_tokens = calculate_cost(input_tokens, output_tokens, cached_tokens, model_name)
                        delta_input = positive_diff(input_tokens, previous_input_tokens)
                        delta_cached = min(
                            delta_input,
                            positive_diff(cached_tokens, previous_cached_tokens),
                        )
                        prompt_growth_tokens = calculate_cost(
                            delta_input,
                            output_tokens,
                            delta_cached,
                            model_name,
                        )
                        attribution_tokens = billed_tokens if segment_start else prompt_growth_tokens

                        prompt_diff = signed_diff(input_tokens, previous_input_tokens)
                        cached_diff = signed_diff(cached_tokens, previous_cached_tokens)
                        limits = model_limits.get(model_name.lower()) or {}
                        max_context_window_tokens = limits.get("max_context_window_tokens") or limits.get("max_prompt_tokens")
                        reserved_response_tokens = attrs.get("maxTokens") or limits.get("max_output_tokens")
                        context_breakdown = build_context_breakdown(
                            input_messages=input_messages,
                            system_prompt_asset=system_prompt_asset,
                            tools_asset=tools_asset,
                            pending_tool_events=pending_tool_events,
                            prompt_tokens=input_tokens,
                            cached_tokens=cached_tokens,
                            max_context_window_tokens=max_context_window_tokens,
                            reserved_response_tokens=reserved_response_tokens,
                        )

                        event = {
                            "id": f"{session_id}:{source_label}:event-{event_sequence}",
                            "kind": "chat",
                            "title": f"chat {model_name}",
                            "model": model_name,
                            "segment_index": source_segment_index,
                            "is_segment_start": segment_start,
                            "boundary_reasons": boundary_reasons,
                            "source": source_label,
                            "ts": ts,
                            "order": event_sequence,
                            "duration_ms": duration_ms,
                            "delta_tokens": prompt_growth_tokens,
                            "attribution_tokens": attribution_tokens,
                            "billed_tokens": billed_tokens,
                            "prompt_tokens": input_tokens,
                            "output_tokens": output_tokens,
                            "cached_tokens": cached_tokens,
                            "uncached_prompt_tokens": max(0.0, input_tokens - cached_tokens),
                            "prompt_diff": prompt_diff,
                            "cached_diff": cached_diff,
                            "observed_counters": {
                                "input": input_tokens,
                                "output": output_tokens,
                                "cached": cached_tokens,
                            },
                            "context_breakdown": context_breakdown,
                            "max_context_window_tokens": max_context_window_tokens,
                            "estimated_tokens": new_token_block(),
                            "carry_forward_tokens": new_token_block(),
                            "ttft_ms": float(attrs.get("ttft", 0) or 0),
                            "debug_name": attrs.get("debugName", ""),
                            "response_id": attrs.get("responseId", ""),
                            "max_tokens": reserved_response_tokens,
                            "request_options": safe_json(parse_json_maybe(attrs.get("requestOptions", ""), attrs.get("requestOptions", ""))),
                            "request_shape": safe_json(parse_json_maybe(attrs.get("requestShape", ""), attrs.get("requestShape", ""))),
                            "system_prompt_id": system_prompt_id,
                            "tools_id": tools_id,
                            "input_messages": input_messages,
                            "new_messages": new_messages,
                            "diff_mode": diff_mode,
                            "response_messages": [],
                            "response_text": "",
                            "reasoning": attrs.get("reasoning", "") or "",
                            "tool_calls_emitted": [],
                        }
                        event_sequence += 1
                        session["events"].append(event)
                        pending_chat_event = event

                        # Use attribution_tokens (not billed_tokens) for session/model totals.
                        # billed_tokens reflects the FULL cumulative input for each call —
                        # summing it across turns would count turn-1 context once per
                        # subsequent call (massive double-counting).
                        # attribution_tokens is either billed_tokens on a true segment
                        # start (first call, model switch, or material prompt drop) or
                        # prompt_growth_tokens (only the net-new input growth + output for
                        # that turn), which gives an accurate aggregate. cache_reset alone
                        # is intentionally not treated as a full-prompt segment boundary.
                        add_token_block(session["totals"], attribution_tokens)
                        # billed_totals sums the raw per-call billed amounts — this matches
                        # what GitHub actually charges (each call billed independently).
                        add_token_block(session["billed_totals"], billed_tokens)
                        session["chat_count"] += 1
                        session["model"] = session["model"] or model_name
                        local_model_totals[model_name]["cost"] += attribution_tokens["cost"]
                        local_model_totals[model_name]["input"] += attribution_tokens["input"]
                        local_model_totals[model_name]["uncached"] += attribution_tokens["uncached"]
                        local_model_totals[model_name]["output"] += attribution_tokens["output"]
                        local_model_totals[model_name]["cached"] += attribution_tokens["cached"]

                        session["latest_prompt_tokens"] = input_tokens
                        session["latest_cached_tokens"] = cached_tokens
                        session["latest_context_breakdown"] = context_breakdown
                        if input_tokens >= session["peak_prompt_tokens"]:
                            session["peak_prompt_tokens"] = input_tokens
                            session["peak_prompt_event_id"] = event["id"]

                        model_bucket = ensure_model_bucket(analysis, model_name)
                        model_bucket["count"] += 1
                        model_bucket["duration_ms"] += duration_ms
                        model_bucket["ttft_ms"] += event["ttft_ms"]
                        model_bucket["input"] += attribution_tokens["input"]
                        model_bucket["uncached"] += attribution_tokens["uncached"]
                        model_bucket["output"] += attribution_tokens["output"]
                        model_bucket["cached"] += attribution_tokens["cached"]
                        model_bucket["cost"] += attribution_tokens["cost"]
                        model_bucket["session_ids"].add(session_id)

                        contributors = build_input_contributors(
                            new_messages=new_messages,
                            pending_user_events=pending_user_events,
                            pending_tool_events=pending_tool_events,
                            previous_chat_event=None if boundary_reasons else previous_chat_event,
                            system_prompt_asset=system_prompt_asset,
                            tools_asset=tools_asset,
                            system_prompt_changed=system_prompt_changed,
                            tools_changed=tools_changed,
                        )
                        used_context_breakdown = allocate_delta_to_context_breakdown(
                            context_breakdown,
                            attribution_tokens,
                            analysis,
                            session,
                        )
                        allocate_delta_to_contributors(
                            contributors,
                            attribution_tokens,
                            analysis,
                            session,
                            record_overhead=not used_context_breakdown,
                        )

                        pending_user_events = []
                        pending_tool_events = []
                        previous_messages = input_messages
                        previous_system_prompt_id = system_prompt_id
                        previous_tools_id = tools_id
                        previous_input_tokens = input_tokens
                        previous_cached_tokens = cached_tokens
                        previous_model_name = model_name
                        continue

                    if entry_type == "agent_response":
                        response_messages = parse_message_list(attrs.get("response", []))
                        response_text = message_list_to_text(response_messages)
                        reasoning = attrs.get("reasoning", "") or ""
                        if pending_chat_event is not None:
                            pending_chat_event["response_messages"] = response_messages
                            pending_chat_event["response_text"] = response_text
                            pending_chat_event["reasoning"] = reasoning
                            pending_chat_event["title"] = build_chat_title(pending_chat_event["model"], reasoning)
                            pending_chat_event["tool_calls_emitted"] = [
                                {
                                    "name": part.get("tool_name") or "tool",
                                    "arguments": part.get("arguments_pretty") or part.get("text") or "",
                                }
                                for message in response_messages
                                for part in message.get("parts", [])
                                if part.get("type") == "tool_call"
                            ]
                            previous_chat_event = pending_chat_event
                            pending_chat_event = None
                        continue
        except IOError:
            continue

    if not session["chat_count"]:
        return None

    if not session["title"]:
        first_user = next((event for event in session["events"] if event["kind"] == "user_message"), None)
        first_chat = next((event for event in session["events"] if event["kind"] == "chat"), None)
        if first_user and first_user.get("content"):
            session["title"] = shorten(first_user["content"].splitlines()[0], 100)
        elif first_chat:
            session["title"] = first_chat["title"]
        else:
            session["title"] = "Untitled chat"

    if local_model_totals:
        session["model"] = max(
            local_model_totals.items(),
            key=lambda item: (item[1]["cost"], item[1]["input"]),
        )[0]
        session["model_names"] = [
            model_name
            for model_name, _bucket in sorted(
                local_model_totals.items(),
                key=lambda item: (item[1]["cost"], item[1]["input"]),
                reverse=True,
            )
        ]

    session["boundary_counts"] = {
        "model_switch": boundary_counts.get("model_switch", 0),
        "context_reset": boundary_counts.get("context_reset", 0),
        "cache_reset": boundary_counts.get("cache_reset", 0),
    }

    session["events"].sort(key=lambda event: (event.get("ts", 0), event.get("order", 0)))
    session["cache_hit_rate"] = (
        (session["totals"]["cached"] / session["totals"]["input"] * 100.0)
        if session["totals"]["input"]
        else 0.0
    )

    # Compute session duration (first to last event timestamp)
    timestamps = [event.get("ts", 0) for event in session["events"] if event.get("ts")]
    if len(timestamps) >= 2:
        session["duration_ms"] = max(timestamps) - min(timestamps)
    elif timestamps:
        session["duration_ms"] = 0.0
    else:
        session["duration_ms"] = 0.0

    return session
