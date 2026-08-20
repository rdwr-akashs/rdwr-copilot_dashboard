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
from per_chat_calculations import *

def build_tool_catalog(
    asset_store: dict[str, dict[str, Any]],
    tool_buckets: dict[str, dict[str, Any]],
    sessions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    toolset_tools: dict[str, dict[str, float]] = {}

    for asset in asset_store.get("toolSets", {}).values():
        definitions = asset.get("definitions")
        if not isinstance(definitions, list):
            continue

        asset_id = asset.get("id", "")
        seen_names_in_asset: set[str] = set()
        tool_tokens_in_asset: dict[str, float] = {}
        for item in definitions:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue

            # Description text is the part that is most actionable for toolset trimming.
            # Keep the estimate description-based rather than whole-schema-based so the
            # waste table ranks verbose, rarely-used tools without blaming shared JSON
            # syntax or provider formatting overhead on every tool.
            description = flatten_text(item.get("description") or "").strip()
            description_tokens = estimate_tokens(description) if description else 0

            entry = catalog.setdefault(
                name,
                {
                    "name": name,
                    "description": "",
                    "descriptionTokens": 0,
                    "toolSetIds": set(),
                },
            )

            if description_tokens >= entry["descriptionTokens"] and description:
                entry["description"] = description
                entry["descriptionTokens"] = description_tokens

            tool_tokens_in_asset[name] = max(float(description_tokens), float(tool_tokens_in_asset.get(name, 0.0)))
            seen_names_in_asset.add(name)

        for name in seen_names_in_asset:
            catalog[name]["toolSetIds"].add(asset_id)
        if asset_id:
            toolset_tools[asset_id] = tool_tokens_in_asset

    for tool_name in tool_buckets.keys():
        catalog.setdefault(
            tool_name,
            {
                "name": tool_name,
                "description": "",
                "descriptionTokens": 0,
                "toolSetIds": set(),
            },
        )

    waste_by_tool: dict[str, dict[str, float]] = collections.defaultdict(lambda: {
        "presentCount": 0.0,
        "usedWhenPresentCount": 0.0,
        "unusedPresentCount": 0.0,
        "wastedInputTokens": 0.0,
        "wastedUncachedTokens": 0.0,
        "wastedCachedTokens": 0.0,
    })

    for session in sessions or []:
        for event in session.get("events", []):
            if event.get("kind") != "chat":
                continue
            tools_id = event.get("tools_id")
            tools_in_set = toolset_tools.get(tools_id or "")
            if not tools_in_set:
                continue

            used_tools = {
                str(tool.get("name") or "").strip()
                for tool in event.get("tool_calls_emitted", [])
                if str(tool.get("name") or "").strip()
            }
            prompt_tokens = float(event.get("prompt_tokens", 0.0) or 0.0)
            cached_tokens = float(event.get("cached_tokens", 0.0) or 0.0)
            cached_ratio = min(1.0, max(0.0, cached_tokens / prompt_tokens)) if prompt_tokens else 0.0

            for name, description_tokens in tools_in_set.items():
                stats = waste_by_tool[name]
                stats["presentCount"] += 1.0
                if name in used_tools:
                    stats["usedWhenPresentCount"] += 1.0
                    continue

                wasted_input = float(description_tokens or 0.0)
                wasted_cached = wasted_input * cached_ratio
                stats["unusedPresentCount"] += 1.0
                stats["wastedInputTokens"] += wasted_input
                stats["wastedCachedTokens"] += wasted_cached
                stats["wastedUncachedTokens"] += max(0.0, wasted_input - wasted_cached)

    catalog_rows: list[dict[str, Any]] = []
    for name, entry in catalog.items():
        bucket = tool_buckets.get(name, {})
        waste = waste_by_tool.get(name, {})
        present_count = int(waste.get("presentCount", 0) or 0)
        unused_count = int(waste.get("unusedPresentCount", 0) or 0)
        catalog_rows.append(
            {
                "name": name,
                "description": entry.get("description", ""),
                "descriptionTokens": entry.get("descriptionTokens", 0),
                "toolSetCount": len(entry.get("toolSetIds", set())),
                "callCount": int(bucket.get("count", 0) or 0),
                "sessionCount": _bucket_session_count(bucket),
                "presentCount": present_count,
                "usedWhenPresentCount": int(waste.get("usedWhenPresentCount", 0) or 0),
                "unusedPresentCount": unused_count,
                "wastePercent": (unused_count / present_count * 100.0) if present_count else 0.0,
                "wastedInputTokens": waste.get("wastedInputTokens", 0.0) or 0.0,
                "wastedUncachedTokens": waste.get("wastedUncachedTokens", 0.0) or 0.0,
                "wastedCachedTokens": waste.get("wastedCachedTokens", 0.0) or 0.0,
            }
        )

    catalog_rows.sort(
        key=lambda item: (
            -float(item.get("wastedInputTokens", 0) or 0),
            -float(item.get("wastePercent", 0) or 0),
            -int(item.get("descriptionTokens", 0) or 0),
            str(item.get("name", "")).lower(),
        )
    )
    return catalog_rows


def month_key_from_timestamp(ts: float | int | None) -> str | None:
    if not ts:
      return None
    try:
      return datetime.fromtimestamp(float(ts) / 1000.0).strftime("%Y-%m")
    except Exception:
      return None


def month_label(month_key: str | None) -> str:
    if not month_key:
      return "Unknown month"
    try:
      return datetime.strptime(month_key, "%Y-%m").strftime("%B %Y")
    except Exception:
      return str(month_key)


def build_period_summary(sessions: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {
        "sessionCount": len(sessions),
        "chatCallCount": 0,
        "toolCallCount": 0,
        "messageCount": 0,
        "modelCount": 0,
        "segmentCount": 0,
        "modelSwitchCount": 0,
        "contextResetCount": 0,
        "totals": new_token_block(),
        "billedTotals": new_token_block(),
        "peakPromptTokens": 0.0,
    }

    model_names: set[str] = set()
    for session in sessions:
        summary["chatCallCount"] += int(session.get("chat_count", 0) or 0)
        summary["toolCallCount"] += int(session.get("tool_count", 0) or 0)
        summary["messageCount"] += int(session.get("message_count", 0) or 0)
        summary["segmentCount"] += int(session.get("segment_count", 0) or 0)
        summary["modelSwitchCount"] += int(session.get("boundary_counts", {}).get("model_switch", 0) or 0)
        summary["contextResetCount"] += int(session.get("boundary_counts", {}).get("context_reset", 0) or 0)
        summary["peakPromptTokens"] = max(summary["peakPromptTokens"], float(session.get("peak_prompt_tokens", 0.0) or 0.0))
        add_token_block(summary["totals"], session.get("totals", {}))
        add_token_block(summary["billedTotals"], session.get("billed_totals", {}))

        names = session.get("model_names") or []
        if names:
            model_names.update(str(name) for name in names if name)
        elif session.get("model"):
            model_names.add(str(session.get("model")))

    summary["modelCount"] = len(model_names)
    summary["cacheHitRate"] = (
        summary["totals"]["cached"] / summary["totals"]["input"] * 100.0
        if summary["totals"]["input"]
        else 0.0
    )
    summary["aiCredits"] = summary["totals"]["cost"] / 0.01 if summary["totals"]["cost"] else 0.0
    summary["billedCredits"] = summary["billedTotals"]["cost"] / 0.01 if summary["billedTotals"]["cost"] else 0.0
    return summary


def build_telemetry_sections() -> list[dict[str, Any]]:
    return [
      {
        "name": "Observed today",
        "items": [
          "Model name, response ID, debug name",
          "Cumulative input / output / cached token counters",
          "Request duration and TTFT",
          "System prompt file and tool-definition file references",
          "Full user / assistant / tool message payloads in inputMessages",
          "Assistant reasoning text when Copilot records it",
          "Executed tool name, args, result, duration, status",
          "File paths for read/edit tools when present in args or patch",
        ],
      },
      {
        "name": "Not exposed directly by current Copilot telemetry",
        "items": [
          "Exact per-message token counts",
          "Exact per-tool token counts",
          "Provider cache-write token counts when Copilot does not emit them",
          "Explicit compaction / summarization events in debug logs (the dashboard infers context resets from prompt resets/shrinks)",
          "Exact per-file token attribution",
          "Exact split between tool payload vs file payload within one tool turn (dashboard uses a mode-aware estimate)",
          "Ground-truth cost split by tool or file (only estimable)",
        ],
      },
    ]


def _new_analysis_state() -> dict[str, Any]:
    return {
      "models": {},
      "tools": {},
      "files": {},
      "overhead": new_overhead_buckets(),
      "chat_events": [],
      "tool_events": [],
      # Tool-catalog accumulation (mergeable across sessions).
      "cat_desc": {},          # tool_name -> {"description", "descriptionTokens"}
      "cat_toolsetids": {},    # tool_name -> set(asset_ids)
      "cat_waste": {},         # tool_name -> waste counters
    }


def _new_waste_bucket() -> dict[str, float]:
    return {
      "presentCount": 0.0,
      "usedWhenPresentCount": 0.0,
      "unusedPresentCount": 0.0,
      "wastedInputTokens": 0.0,
      "wastedUncachedTokens": 0.0,
      "wastedCachedTokens": 0.0,
    }


_TOKEN_KEYS = ("input", "uncached", "output", "cached", "cost")
_IDENTITY_FACTORS = {key: 1.0 for key in _TOKEN_KEYS}


def _token_scale_factors(attr_block: dict[str, Any] | None, billed_block: dict[str, Any] | None) -> dict[str, float]:
    """Per-category billed/attributed scale factors (mirrors the old client logic)."""
    source = attr_block or {}
    target = billed_block or source
    factors: dict[str, float] = {}
    for key in _TOKEN_KEYS:
      frm = float(source.get(key, 0.0) or 0.0)
      to = float(target.get(key, 0.0) or 0.0)
      if frm > 0:
        factors[key] = to / frm
      elif to > 0:
        factors[key] = 1.0
      else:
        factors[key] = 0.0
    return factors


def _scaled_token_block(block: dict[str, Any] | None, factors: dict[str, float], scale: float = 1.0) -> dict[str, float]:
    src = block or {}
    return {key: float(src.get(key, 0.0) or 0.0) * float(factors.get(key, 0.0)) * scale for key in _TOKEN_KEYS}


def _accumulate_session_into_analysis_state(
    state: dict[str, Any],
    session: dict[str, Any],
    asset_store: dict[str, dict[str, Any]],
    billed: bool = False,
    build_catalog: bool = True,
  ) -> None:
    """Fold a single fully-parsed session (with events) into a mergeable analysis state.

    When ``billed`` is true, per-call token blocks use billed usage and tool/file/
    overhead estimates are scaled by this session's billed/attributed factors,
    matching the previous client-side billed recomputation.
    """
    factors = _IDENTITY_FACTORS if not billed else _token_scale_factors(session.get("totals"), session.get("billed_totals"))

    for key, block in (session.get("overhead") or {}).items():
      if key in state["overhead"] and isinstance(block, dict):
        if billed:
          add_token_block(state["overhead"][key], _scaled_token_block(block, factors))
        else:
          add_token_block(state["overhead"][key], block)

    session_id = str(session.get("id") or "")
    session_title = session.get("title") or "Untitled chat"

    # Build this session's toolset description map (used for unused-tool waste).
    toolset_tools: dict[str, dict[str, float]] = {}
    if build_catalog:
      for asset in (asset_store or {}).get("toolSets", {}).values():
        definitions = asset.get("definitions")
        if not isinstance(definitions, list):
          continue
        asset_id = asset.get("id", "")
        tokens_in_asset: dict[str, float] = {}
        for item in definitions:
          if not isinstance(item, dict):
            continue
          name = str(item.get("name") or "").strip()
          if not name:
            continue
          description = flatten_text(item.get("description") or "").strip()
          description_tokens = estimate_tokens(description) if description else 0
          entry = state["cat_desc"].setdefault(name, {"description": "", "descriptionTokens": 0})
          if description_tokens >= entry["descriptionTokens"] and description:
            entry["description"] = description
            entry["descriptionTokens"] = description_tokens
          tokens_in_asset[name] = max(float(description_tokens), float(tokens_in_asset.get(name, 0.0)))
          state["cat_toolsetids"].setdefault(name, set()).add(asset_id)
        if asset_id:
          toolset_tools[asset_id] = tokens_in_asset

    for event in session.get("events", []):
      kind = event.get("kind")
      if kind == "chat":
        model_name = str(event.get("model") or "unknown")
        if billed:
          chat_block = event.get("billed_tokens") or event.get("attribution_tokens") or new_token_block()
        else:
          chat_block = event.get("attribution_tokens") or event.get("billed_tokens") or new_token_block()

        model_bucket = ensure_model_bucket(state, model_name)
        model_bucket["count"] += 1
        model_bucket["duration_ms"] += float(event.get("duration_ms", 0.0) or 0.0)
        model_bucket["ttft_ms"] += float(event.get("ttft_ms", 0.0) or 0.0)
        add_token_block(model_bucket, chat_block)
        model_bucket["session_ids"].add(session_id)

        state["chat_events"].append(
          {
            "sessionId": session_id,
            "sessionTitle": session_title,
            "model": model_name,
            "title": event.get("title") or f"chat {model_name}",
            "durationMs": float(event.get("duration_ms", 0.0) or 0.0),
            "cost": float(chat_block.get("cost", 0.0) or 0.0),
            "input": float(chat_block.get("input", 0.0) or 0.0),
            "uncached": float(chat_block.get("uncached", 0.0) or 0.0),
            "output": float(chat_block.get("output", 0.0) or 0.0),
            "cached": float(chat_block.get("cached", 0.0) or 0.0),
            "promptTokens": float(event.get("prompt_tokens", 0.0) or 0.0),
            "timestamp": event.get("ts"),
          }
        )

        # Unused-tool waste for this chat call (mode-independent; billed scaling
        # is applied globally at finalize).
        if build_catalog:
          tools_in_set = toolset_tools.get(event.get("tools_id") or "")
          if tools_in_set:
            used_tools = {
              str(tool.get("name") or "").strip()
              for tool in event.get("tool_calls_emitted", [])
              if str(tool.get("name") or "").strip()
            }
            prompt_tokens = float(event.get("prompt_tokens", 0.0) or 0.0)
            cached_tokens = float(event.get("cached_tokens", 0.0) or 0.0)
            cached_ratio = min(1.0, max(0.0, cached_tokens / prompt_tokens)) if prompt_tokens else 0.0
            for name, description_tokens in tools_in_set.items():
              stats = state["cat_waste"].setdefault(name, _new_waste_bucket())
              stats["presentCount"] += 1.0
              if name in used_tools:
                stats["usedWhenPresentCount"] += 1.0
                continue
              wasted_input = float(description_tokens or 0.0)
              wasted_cached = wasted_input * cached_ratio
              stats["unusedPresentCount"] += 1.0
              stats["wastedInputTokens"] += wasted_input
              stats["wastedCachedTokens"] += wasted_cached
              stats["wastedUncachedTokens"] += max(0.0, wasted_input - wasted_cached)
        continue

      if kind != "tool":
        continue

      tool_name = str(event.get("name") or "unknown")
      mode = str(event.get("mode") or "other")
      raw_estimated = event.get("estimated_tokens") or new_token_block()
      estimated_tokens = _scaled_token_block(raw_estimated, factors) if billed else raw_estimated
      payload_tokens = float(event.get("payload_tokens_estimate", 0.0) or 0.0)

      tool_bucket = ensure_tool_bucket(state, tool_name, mode)
      tool_bucket["count"] += 1
      tool_bucket["duration_ms"] += float(event.get("duration_ms", 0.0) or 0.0)
      tool_bucket["errors"] += 0 if event.get("status") == "ok" else 1
      tool_bucket["payload_tokens_estimate"] += payload_tokens
      add_token_block(tool_bucket, estimated_tokens)
      tool_bucket["session_ids"].add(session_id)

      state["tool_events"].append(
        {
          "sessionId": session_id,
          "sessionTitle": session_title,
          "name": tool_name,
          "title": event.get("title") or tool_name,
          "durationMs": float(event.get("duration_ms", 0.0) or 0.0),
          "status": event.get("status", "unknown"),
          "estimated": estimated_tokens,
          "timestamp": event.get("ts"),
        }
      )

      file_paths = [path for path in (event.get("files") or []) if isinstance(path, str) and path]
      if not file_paths:
        continue

      file_share = 1.0 / float(len(file_paths))
      for file_path in file_paths:
        file_bucket = ensure_file_bucket(state, file_path)
        file_bucket["session_ids"].add(session_id)
        file_bucket["tools"].add(tool_name)
        file_bucket["payload_tokens_estimate"] += payload_tokens * file_share
        file_bucket["tool_reference_count"] += 1
        if mode == "read":
          file_bucket["read_count"] += 1
        elif mode == "edit":
          file_bucket["edit_count"] += 1

        add_token_block(file_bucket, estimated_tokens, file_share)
        usage_key = f"{tool_name}::{mode}"
        usage_bucket = file_bucket["tool_usage"].get(usage_key)
        if usage_bucket is None:
          usage_bucket = make_file_tool_usage_bucket(tool_name, mode)
          file_bucket["tool_usage"][usage_key] = usage_bucket
        usage_bucket["count"] += 1
        usage_bucket["duration_ms"] += float(event.get("duration_ms", 0.0) or 0.0)
        usage_bucket["payload_tokens_estimate"] += payload_tokens * file_share
        add_token_block(usage_bucket, estimated_tokens, file_share)
        usage_bucket["session_ids"].add(session_id)



def _finalize_tool_catalog(state: dict[str, Any], waste_factors: dict[str, float] | None = None) -> list[dict[str, Any]]:
    names = set(state["cat_desc"].keys()) | set(state["tools"].keys()) | set(state["cat_waste"].keys())
    wf = waste_factors or {}
    f_input = float(wf.get("input", 1.0))
    f_uncached = float(wf.get("uncached", 1.0))
    f_cached = float(wf.get("cached", 1.0))
    rows: list[dict[str, Any]] = []
    for name in names:
      desc = state["cat_desc"].get(name, {"description": "", "descriptionTokens": 0})
      bucket = state["tools"].get(name, {})
      waste = state["cat_waste"].get(name, {})
      present_count = int(waste.get("presentCount", 0) or 0)
      unused_count = int(waste.get("unusedPresentCount", 0) or 0)
      rows.append(
        {
          "name": name,
          "description": desc.get("description", ""),
          "descriptionTokens": desc.get("descriptionTokens", 0),
          "toolSetCount": len(state["cat_toolsetids"].get(name, set())),
          "callCount": int(bucket.get("count", 0) or 0),
          "sessionCount": _bucket_session_count(bucket),
          "presentCount": present_count,
          "usedWhenPresentCount": int(waste.get("usedWhenPresentCount", 0) or 0),
          "unusedPresentCount": unused_count,
          "wastePercent": (unused_count / present_count * 100.0) if present_count else 0.0,
          "wastedInputTokens": (waste.get("wastedInputTokens", 0.0) or 0.0) * f_input,
          "wastedUncachedTokens": (waste.get("wastedUncachedTokens", 0.0) or 0.0) * f_uncached,
          "wastedCachedTokens": (waste.get("wastedCachedTokens", 0.0) or 0.0) * f_cached,
        }
      )
    rows.sort(
      key=lambda item: (
        -float(item.get("wastedInputTokens", 0) or 0),
        -float(item.get("wastePercent", 0) or 0),
        -int(item.get("descriptionTokens", 0) or 0),
        str(item.get("name", "")).lower(),
      )
    )
    return rows


def _bucket_session_count(bucket: dict[str, Any]) -> int:
    if "session_count" in bucket:
      return int(bucket.get("session_count", 0) or 0)
    return len(bucket.get("session_ids") or set())


def _finalize_analysis_state(
    state: dict[str, Any],
    telemetry_fields: set[str],
    entry_types: collections.Counter,
    monthly_trends: list[dict[str, Any]] | None = None,
    waste_factors: dict[str, float] | None = None,
  ) -> dict[str, Any]:
    chat_events = state["chat_events"]
    tool_events = state["tool_events"]

    models: list[dict[str, Any]] = []
    for model_name, bucket in state["models"].items():
      cache_hit_rate = (bucket["cached"] / bucket["input"] * 100.0) if bucket["input"] else 0.0
      models.append(
        {
          "name": model_name,
          "count": bucket["count"],
          "sessionCount": _bucket_session_count(bucket),
          "durationMs": bucket["duration_ms"],
          "avgDurationMs": bucket["duration_ms"] / bucket["count"] if bucket["count"] else 0.0,
          "avgTtftMs": bucket["ttft_ms"] / bucket["count"] if bucket["count"] else 0.0,
          "input": bucket["input"],
          "uncached": bucket["uncached"],
          "output": bucket["output"],
          "cached": bucket["cached"],
          "cost": bucket["cost"],
          "cacheHitRate": cache_hit_rate,
        }
      )
    models.sort(key=lambda item: (item["cost"], item["input"]), reverse=True)

    tools: list[dict[str, Any]] = []
    for tool_name, bucket in state["tools"].items():
      tools.append(
        {
          "name": tool_name,
          "mode": bucket["mode"],
          "count": bucket["count"],
          "sessionCount": _bucket_session_count(bucket),
          "errors": bucket["errors"],
          "durationMs": bucket["duration_ms"],
          "avgDurationMs": bucket["duration_ms"] / bucket["count"] if bucket["count"] else 0.0,
          "payloadTokens": bucket["payload_tokens_estimate"],
          "avgPayloadTokens": bucket["payload_tokens_estimate"] / bucket["count"] if bucket["count"] else 0.0,
          "input": bucket["input"],
          "uncached": bucket["uncached"],
          "output": bucket["output"],
          "cached": bucket["cached"],
          "cost": bucket["cost"],
          "avgInput": bucket["input"] / bucket["count"] if bucket["count"] else 0.0,
          "avgOutput": bucket["output"] / bucket["count"] if bucket["count"] else 0.0,
          "avgCached": bucket["cached"] / bucket["count"] if bucket["count"] else 0.0,
          "avgCost": bucket["cost"] / bucket["count"] if bucket["count"] else 0.0,
        }
      )
    tools.sort(key=lambda item: (item["cost"], item["count"], item["durationMs"]), reverse=True)

    files: list[dict[str, Any]] = []
    for path, bucket in state["files"].items():
      if bucket["cost"] <= 0:
        continue
      total_ops = bucket["read_count"] + bucket["edit_count"]
      tool_usage_rows: list[dict[str, Any]] = []
      for usage in bucket.get("tool_usage", {}).values():
        count = int(usage.get("count", 0) or 0)
        duration_ms = float(usage.get("duration_ms", 0.0) or 0.0)
        payload_tokens = float(usage.get("payload_tokens_estimate", 0.0) or 0.0)
        tool_usage_rows.append(
          {
            "name": usage.get("name", "unknown"),
            "mode": usage.get("mode", "other"),
            "count": count,
            "sessionCount": _bucket_session_count(usage),
            "durationMs": duration_ms,
            "avgDurationMs": duration_ms / count if count else 0.0,
            "payloadTokens": payload_tokens,
            "avgPayloadTokens": payload_tokens / count if count else 0.0,
            "input": float(usage.get("input", 0.0) or 0.0),
            "uncached": float(usage.get("uncached", 0.0) or 0.0),
            "output": float(usage.get("output", 0.0) or 0.0),
            "cached": float(usage.get("cached", 0.0) or 0.0),
            "cost": float(usage.get("cost", 0.0) or 0.0),
            "avgInput": float(usage.get("input", 0.0) or 0.0) / count if count else 0.0,
            "avgOutput": float(usage.get("output", 0.0) or 0.0) / count if count else 0.0,
            "avgCached": float(usage.get("cached", 0.0) or 0.0) / count if count else 0.0,
            "avgCost": float(usage.get("cost", 0.0) or 0.0) / count if count else 0.0,
          }
        )
      tool_usage_rows.sort(key=lambda item: (item["cost"], item["count"], item["durationMs"]), reverse=True)
      files.append(
        {
          "path": path,
          "shortPath": short_path(path),
          "name": os.path.basename(path) or path,
          "readCount": bucket["read_count"],
          "editCount": bucket["edit_count"],
          "sessionCount": _bucket_session_count(bucket),
          "payloadTokens": bucket["payload_tokens_estimate"],
          "avgInput": bucket["input"] / total_ops if total_ops else 0.0,
          "avgOutput": bucket["output"] / total_ops if total_ops else 0.0,
          "avgCached": bucket["cached"] / total_ops if total_ops else 0.0,
          "avgCost": bucket["cost"] / total_ops if total_ops else 0.0,
          "input": bucket["input"],
          "uncached": bucket["uncached"],
          "output": bucket["output"],
          "cached": bucket["cached"],
          "cost": bucket["cost"],
          "tools": sorted(bucket["tools"]),
          "toolUsage": tool_usage_rows,
          "toolReferenceCount": int(bucket.get("tool_reference_count", 0) or 0),
        }
      )
    files.sort(key=lambda item: (item["cost"], item["readCount"] + item["editCount"], item["payloadTokens"]), reverse=True)

    chat_events.sort(key=lambda item: (item["cost"], item["input"]), reverse=True)
    tool_events.sort(key=lambda item: (item["estimated"]["cost"], item["durationMs"]), reverse=True)

    tool_catalog = _finalize_tool_catalog(state, waste_factors)
    telemetry_sections = build_telemetry_sections()

    return {
      "models": models,
      "tools": tools,
      "toolCatalog": tool_catalog,
      "files": files,
      "topChats": chat_events[:12],
      "slowestTools": sorted(tool_events, key=lambda item: item["durationMs"], reverse=True)[:12],
      "overhead": {
        key: value for key, value in state["overhead"].items()
      },
      "telemetry": {
        "sections": telemetry_sections,
        "observedFields": sorted(telemetry_fields),
        "entryTypes": dict(entry_types),
      },
      "monthlyTrends": monthly_trends or [],
    }


def build_analysis_output(
    sessions: list[dict[str, Any]],
    asset_store: dict[str, dict[str, Any]],
    telemetry_fields: set[str],
    entry_types: collections.Counter,
    monthly_trends: list[dict[str, Any]] | None = None,
    billed: bool = False,
    waste_factors: dict[str, float] | None = None,
  ) -> dict[str, Any]:
    """Event-based analysis: accumulate fully-parsed sessions, then finalize."""
    state = _new_analysis_state()
    for session in sessions:
      _accumulate_session_into_analysis_state(state, session, asset_store, billed=billed)
    return _finalize_analysis_state(state, telemetry_fields, entry_types, monthly_trends, waste_factors)


def _serialize_token_block(block: dict[str, Any] | None) -> dict[str, float]:
    src = block or {}
    return {
      "input": float(src.get("input", 0.0) or 0.0),
      "uncached": float(src.get("uncached", 0.0) or 0.0),
      "output": float(src.get("output", 0.0) or 0.0),
      "cached": float(src.get("cached", 0.0) or 0.0),
      "cost": float(src.get("cost", 0.0) or 0.0),
    }


def _compact_token_block(block: dict[str, Any] | None) -> list[float]:
    src = block or {}
    return [
      float(src.get("input", 0.0) or 0.0),
      float(src.get("uncached", 0.0) or 0.0),
      float(src.get("output", 0.0) or 0.0),
      float(src.get("cached", 0.0) or 0.0),
      float(src.get("cost", 0.0) or 0.0),
    ]


def _serialize_analysis_buckets(state: dict[str, Any]) -> dict[str, Any]:
    """Serialize the mode-dependent (mergeable) buckets of an analysis state."""
    models = {}
    for name, bucket in state["models"].items():
      models[name] = _compact_token_block(bucket) + [
        bucket["count"],
        bucket["duration_ms"],
        bucket["ttft_ms"],
        len(bucket["session_ids"]),
      ]

    tools = {}
    for name, bucket in state["tools"].items():
      tools[name] = _compact_token_block(bucket) + [
        bucket["mode"],
        bucket["count"],
        bucket["duration_ms"],
        bucket["errors"],
        bucket["payload_tokens_estimate"],
        len(bucket["session_ids"]),
      ]

    files = {}
    for path, bucket in state["files"].items():
      if float(bucket.get("cost", 0.0) or 0.0) <= 0:
        continue
      tool_usage = []
      for usage in bucket.get("tool_usage", {}).values():
        tool_usage.append(
          [
            usage.get("name", "unknown"),
            usage.get("mode", "other"),
            usage.get("count", 0),
            usage.get("duration_ms", 0.0),
            usage.get("payload_tokens_estimate", 0.0),
            len(usage.get("session_ids") or []),
            *_compact_token_block(usage),
          ]
        )
      tool_usage.sort(key=lambda item: (item[10], item[2], item[3]), reverse=True)
      files[path] = _compact_token_block(bucket) + [
        bucket["read_count"],
        bucket["edit_count"],
        bucket["payload_tokens_estimate"],
        sorted(bucket["tools"]),
        len(bucket["session_ids"]),
        bucket.get("tool_reference_count", 0),
        tool_usage,
      ]

    def short_event_text(value: Any, limit: int) -> str:
      text = "" if value is None else str(value)
      if len(text) <= limit:
        return text
      return text[: max(0, limit - 3)].rstrip() + "..."

    def compact_ranked_event(event: dict[str, Any]) -> dict[str, Any]:
      compact = dict(event)
      if "title" in compact:
        compact["title"] = short_event_text(compact.get("title", ""), 120)
      if "sessionTitle" in compact:
        compact["sessionTitle"] = short_event_text(compact.get("sessionTitle", ""), 100)
      return compact

    chat_events = [
      compact_ranked_event(event)
      for event in sorted(state["chat_events"], key=lambda item: (item["cost"], item["input"]), reverse=True)[:12]
    ]
    tool_events = [
      compact_ranked_event(event)
      for event in sorted(state["tool_events"], key=lambda item: item["durationMs"], reverse=True)[:12]
    ]

    return {
      "overhead": {key: _compact_token_block(block) for key, block in state["overhead"].items()},
      "models": models,
      "tools": tools,
      "files": files,
      "chatEvents": chat_events,
      "toolEvents": tool_events,
    }


def compute_session_contribution(
    session: dict[str, Any],
    asset_store: dict[str, dict[str, Any]],
  ) -> dict[str, Any]:
    """Pre-compute the per-session analysis contribution for both token modes.

    The result is mergeable across sessions and free of per-event detail, so the
    Analysis tab can be rebuilt without loading the heavy full-session payloads.
    """
    attr_state = _new_analysis_state()
    _accumulate_session_into_analysis_state(attr_state, session, asset_store, billed=False, build_catalog=True)

    billed_state = _new_analysis_state()
    _accumulate_session_into_analysis_state(billed_state, session, asset_store, billed=True, build_catalog=False)

    compact_tool_desc = {
      name: int(desc.get("descriptionTokens", 0) or 0)
      for name, desc in attr_state["cat_desc"].items()
    }
    compact_tool_waste = {
      name: [
        float(waste.get("presentCount", 0.0) or 0.0),
        float(waste.get("usedWhenPresentCount", 0.0) or 0.0),
        float(waste.get("unusedPresentCount", 0.0) or 0.0),
        float(waste.get("wastedInputTokens", 0.0) or 0.0),
        float(waste.get("wastedUncachedTokens", 0.0) or 0.0),
        float(waste.get("wastedCachedTokens", 0.0) or 0.0),
      ]
      for name, waste in attr_state["cat_waste"].items()
    }

    return {
      "attr": _serialize_analysis_buckets(attr_state),
      "billed": _serialize_analysis_buckets(billed_state),
      # Tool catalog inputs are mode-independent (waste scaling happens globally).
      "catDesc": compact_tool_desc,
      "catToolsetIds": {name: sorted(ids) for name, ids in attr_state["cat_toolsetids"].items()},
      "catWaste": compact_tool_waste,
    }


def _merge_contribution_into_analysis_state(
    state: dict[str, Any],
    contribution: dict[str, Any],
    mode: str = "attr",
  ) -> None:
    if not isinstance(contribution, dict):
      return

    buckets = contribution.get(mode) if isinstance(contribution.get(mode), dict) else contribution

    def merged_session_count(src: dict[str, Any]) -> int:
      if isinstance(src, list):
        return int(src[-1] or 0) if src else 0
      if "session_count" in src:
        return int(src.get("session_count", 0) or 0)
      return len(src.get("session_ids") or [])

    def src_value(src: Any, key: str, index: int, default: Any = 0) -> Any:
      if isinstance(src, list):
        return src[index] if len(src) > index else default
      if isinstance(src, dict):
        return src.get(key, default)
      return default

    def add_serialized_token_block(target: dict[str, Any], src: Any) -> None:
      if isinstance(src, list):
        target["input"] += float(src[0] if len(src) > 0 else 0.0)
        target["uncached"] += float(src[1] if len(src) > 1 else 0.0)
        target["output"] += float(src[2] if len(src) > 2 else 0.0)
        target["cached"] += float(src[3] if len(src) > 3 else 0.0)
        target["cost"] += float(src[4] if len(src) > 4 else 0.0)
        return
      if isinstance(src, dict):
        add_token_block(target, src)

    for key, block in (buckets.get("overhead") or {}).items():
      if key in state["overhead"] and isinstance(block, (dict, list)):
        add_serialized_token_block(state["overhead"][key], block)

    for name, src in (buckets.get("models") or {}).items():
      bucket = ensure_model_bucket(state, name)
      bucket["count"] += int(src_value(src, "count", 5, 0) or 0)
      bucket["duration_ms"] += float(src_value(src, "duration_ms", 6, 0.0) or 0.0)
      bucket["ttft_ms"] += float(src_value(src, "ttft_ms", 7, 0.0) or 0.0)
      add_serialized_token_block(bucket, src)
      bucket["session_count"] = int(bucket.get("session_count", 0) or 0) + merged_session_count(src)

    for name, src in (buckets.get("tools") or {}).items():
      bucket = ensure_tool_bucket(state, name, str(src_value(src, "mode", 5, "other") or "other"))
      bucket["count"] += int(src_value(src, "count", 6, 0) or 0)
      bucket["duration_ms"] += float(src_value(src, "duration_ms", 7, 0.0) or 0.0)
      bucket["errors"] += int(src_value(src, "errors", 8, 0) or 0)
      bucket["payload_tokens_estimate"] += float(src_value(src, "payload_tokens_estimate", 9, 0.0) or 0.0)
      add_serialized_token_block(bucket, src)
      bucket["session_count"] = int(bucket.get("session_count", 0) or 0) + merged_session_count(src)

    for path, src in (buckets.get("files") or {}).items():
      bucket = ensure_file_bucket(state, path)
      bucket["read_count"] += int(src_value(src, "read_count", 5, 0) or 0)
      bucket["edit_count"] += int(src_value(src, "edit_count", 6, 0) or 0)
      bucket["payload_tokens_estimate"] += float(src_value(src, "payload_tokens_estimate", 7, 0.0) or 0.0)
      add_serialized_token_block(bucket, src)
      bucket["tools"].update(src_value(src, "tools", 8, []) or [])
      if isinstance(src, list):
        file_session_count = int(src_value(src, "session_count", 9, 0) or 0)
      else:
        file_session_count = merged_session_count(src)
      bucket["session_count"] = int(bucket.get("session_count", 0) or 0) + file_session_count
      bucket["tool_reference_count"] += int(src_value(src, "tool_reference_count", 10, 0) or 0)

      tool_usage_src = src_value(src, "tool_usage", 11, {}) or {}
      if isinstance(tool_usage_src, dict):
        usage_items = tool_usage_src.items()
      elif isinstance(tool_usage_src, list):
        usage_items = (
          (
            f"{src_value(usage, 'name', 0, 'unknown') or 'unknown'}::{src_value(usage, 'mode', 1, 'other') or 'other'}",
            usage,
          )
          for usage in tool_usage_src
          if isinstance(usage, (dict, list))
        )
      else:
        usage_items = []

      for usage_key, usage in usage_items:
        if not isinstance(usage, (dict, list)):
          continue
        tool_name = str(src_value(usage, "name", 0, usage_key.split("::", 1)[0]) or "unknown")
        mode = str(src_value(usage, "mode", 1, (usage_key.split("::", 1)[1] if "::" in usage_key else "other")) or "other")
        target = bucket["tool_usage"].get(usage_key)
        if target is None:
          target = make_file_tool_usage_bucket(tool_name, mode)
          bucket["tool_usage"][usage_key] = target
        target["count"] += int(src_value(usage, "count", 2, 0) or 0)
        target["duration_ms"] += float(src_value(usage, "duration_ms", 3, 0.0) or 0.0)
        target["payload_tokens_estimate"] += float(src_value(usage, "payload_tokens_estimate", 4, 0.0) or 0.0)
        if isinstance(usage, list):
          add_serialized_token_block(target, usage[6:11])
          target["session_count"] = int(target.get("session_count", 0) or 0) + int(src_value(usage, "session_count", 5, 0) or 0)
        else:
          add_serialized_token_block(target, usage)
          target["session_count"] = int(target.get("session_count", 0) or 0) + merged_session_count(usage)

    state["chat_events"].extend(buckets.get("chatEvents") or [])
    state["tool_events"].extend(buckets.get("toolEvents") or [])

    for name, desc in (contribution.get("catDesc") or {}).items():
      entry = state["cat_desc"].setdefault(name, {"description": "", "descriptionTokens": 0})
      if isinstance(desc, dict):
        desc_tokens = int(desc.get("descriptionTokens", 0) or 0)
        if desc_tokens >= entry["descriptionTokens"] and desc.get("description"):
          entry["description"] = desc.get("description", "")
          entry["descriptionTokens"] = desc_tokens
        elif desc_tokens > entry["descriptionTokens"]:
          entry["descriptionTokens"] = desc_tokens
      else:
        desc_tokens = int(desc or 0)
        if desc_tokens > entry["descriptionTokens"]:
          entry["descriptionTokens"] = desc_tokens

    for name, ids in (contribution.get("catToolsetIds") or {}).items():
      state["cat_toolsetids"].setdefault(name, set()).update(ids)

    for name, waste in (contribution.get("catWaste") or {}).items():
      acc = state["cat_waste"].setdefault(name, _new_waste_bucket())
      if isinstance(waste, list):
        for index, waste_key in enumerate(acc.keys()):
          acc[waste_key] += float(waste[index] if len(waste) > index else 0.0)
      elif isinstance(waste, dict):
        for waste_key in acc.keys():
          acc[waste_key] += float(waste.get(waste_key, 0.0) or 0.0)


def aggregate_contributions(
    contributions: list[dict[str, Any]],
    telemetry_fields: set[str],
    entry_types: collections.Counter,
    monthly_trends: list[dict[str, Any]] | None = None,
    mode: str = "attr",
    waste_factors: dict[str, float] | None = None,
  ) -> dict[str, Any]:
    """Build the analysis output by merging pre-computed per-session contributions."""
    state = _new_analysis_state()
    for contribution in contributions:
      _merge_contribution_into_analysis_state(state, contribution, mode=mode)
    return _finalize_analysis_state(state, telemetry_fields, entry_types, monthly_trends, waste_factors)


def build_period_bundle(
    sessions: list[dict[str, Any]],
    asset_store: dict[str, dict[str, Any]],
    telemetry_fields: set[str],
    entry_types: collections.Counter,
    monthly_trends: list[dict[str, Any]] | None = None,
    monthly_trends_billed: list[dict[str, Any]] | None = None,
    contributions_by_id: dict[str, dict[str, Any]] | None = None,
  ) -> dict[str, Any]:
    summary = build_period_summary(sessions)
    billed_waste_factors = _token_scale_factors(summary.get("totals"), summary.get("billedTotals"))

    if contributions_by_id is not None:
      contributions = [
        contributions_by_id[session_id]
        for session in sessions
        if (session_id := str(session.get("id") or "")) in contributions_by_id
      ]
      analysis = aggregate_contributions(
        contributions=contributions,
        telemetry_fields=telemetry_fields,
        entry_types=entry_types,
        monthly_trends=monthly_trends,
        mode="attr",
      )
      analysis_billed = aggregate_contributions(
        contributions=contributions,
        telemetry_fields=telemetry_fields,
        entry_types=entry_types,
        monthly_trends=monthly_trends_billed if monthly_trends_billed is not None else monthly_trends,
        mode="billed",
        waste_factors=billed_waste_factors,
      )
    else:
      analysis = build_analysis_output(
        sessions=sessions,
        asset_store=asset_store,
        telemetry_fields=telemetry_fields,
        entry_types=entry_types,
        monthly_trends=monthly_trends,
        billed=False,
      )
      analysis_billed = build_analysis_output(
        sessions=sessions,
        asset_store=asset_store,
        telemetry_fields=telemetry_fields,
        entry_types=entry_types,
        monthly_trends=monthly_trends_billed if monthly_trends_billed is not None else monthly_trends,
        billed=True,
        waste_factors=billed_waste_factors,
      )
    return {
      "summary": summary,
      "analysis": analysis,
      "analysisBilled": analysis_billed,
      "sessionIds": [session.get("id") for session in sessions if session.get("id")],
    }


def build_monthly_trends(sessions: list[dict[str, Any]], billed: bool = False) -> list[dict[str, Any]]:
    sessions_by_month: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for session in sessions:
      month_key = month_key_from_timestamp(session.get("timestamp"))
      if not month_key:
        continue
      sessions_by_month[month_key].append(session)

    rows: list[dict[str, Any]] = []
    for month_key in sorted(sessions_by_month):
      month_sessions = sessions_by_month[month_key]
      totals = new_token_block()
      model_names: set[str] = set()
      boundary_counts: collections.Counter = collections.Counter()
      chat_call_count = 0
      tool_call_count = 0
      segment_count = 0
      peak_prompt_tokens = 0.0

      for session in month_sessions:
        token_block = session.get("billed_totals") if billed else session.get("totals")
        if not isinstance(token_block, dict):
          token_block = session.get("totals") if isinstance(session.get("totals"), dict) else new_token_block()
        add_token_block(totals, token_block)

        chat_call_count += int(session.get("chat_count", 0) or 0)
        tool_call_count += int(session.get("tool_count", 0) or 0)
        segment_count += int(session.get("segment_count", 0) or 0)
        peak_prompt_tokens = max(peak_prompt_tokens, float(session.get("peak_prompt_tokens", 0.0) or 0.0))

        for model_name in session.get("model_names", []) or []:
          if model_name:
            model_names.add(str(model_name))
        fallback_model = session.get("model")
        if fallback_model:
          model_names.add(str(fallback_model))

        for key, value in (session.get("boundary_counts") or {}).items():
          boundary_counts[str(key)] += int(value or 0)

      input_tokens = float(totals.get("input", 0.0) or 0.0)
      cached_tokens = float(totals.get("cached", 0.0) or 0.0)
      rows.append(
        {
          "monthKey": month_key,
          "label": month_label(month_key),
          "sessionCount": len(month_sessions),
          "chatCallCount": chat_call_count,
          "toolCallCount": tool_call_count,
          "messageCount": chat_call_count,
          "modelCount": len(model_names),
          "segmentCount": segment_count,
          "modelSwitchCount": int(boundary_counts.get("model_switch", 0) or 0),
          "contextResetCount": int(boundary_counts.get("context_reset", 0) or 0),
          "cacheResetCount": int(boundary_counts.get("cache_reset", 0) or 0),
          "totals": dict(totals),
          "peakPromptTokens": peak_prompt_tokens,
          "cacheHitRate": (cached_tokens / input_tokens * 100.0) if input_tokens else 0.0,
          "modelNames": sorted(model_names),
        }
      )
    return rows
