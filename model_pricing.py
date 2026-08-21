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

import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# GitHub Copilot model prices, USD per 1M tokens.
#
# SOURCE OF TRUTH: https://docs.github.com/en/copilot/reference/copilot-billing/models-and-pricing
# (the "Pricing tables" section). Verified against that page on 2026-08-21;
# every value in the "current" block below is quoted from it verbatim. GitHub
# bills Copilot usage in AI credits, where 1 credit = $0.01 USD, priced off
# these same per-token rates (see premium_requests.py), so a dollar figure here
# is 100x the credit figure GitHub charges.
#
# Three documented cost components this table deliberately does NOT model:
#
#   1. Cache writes. Officially priced (see CACHE_WRITE_PRICING below) but VS
#      Code chat telemetry exposes no cache-write counter, so applying it would
#      be guesswork for the chat half of the data. Costs here are therefore a
#      lower bound for cache-heavy sessions. (The CLI's session-store.db *does*
#      carry `cacheWrite` per model bucket - wiring that up is a separate,
#      source-asymmetric change.)
#   2. Long-context tiers. Several models double above a context threshold:
#      GPT-5.4/5.5/5.6-Sol/5.6-Terra above 272K, GPT-5.6-Luna / Gemini 3.1 Pro
#      / Grok 4.5-4.6 above 200K. Neither data source records per-call context
#      size, so only the default (below-threshold) tier is priced.
#   3. The 10% discount on model costs when using auto model selection.
#
# All three make estimates conservative (under-, not over-stated) except where
# a long-context call is mispriced at the default tier.
PRICING = {
    # ---------------- Anthropic ----------------
    "claude-haiku-4.5": {"input": 1.00, "cached": 0.10, "output": 5.00},
    "claude-sonnet-4": {"input": 3.00, "cached": 0.30, "output": 15.00},
    "claude-sonnet-4.5": {"input": 3.00, "cached": 0.30, "output": 15.00},
    "claude-sonnet-4.6": {"input": 3.00, "cached": 0.30, "output": 15.00},
    "claude-sonnet-5": {"input": 2.00, "cached": 0.20, "output": 10.00},
    "claude-opus-4.5": {"input": 5.00, "cached": 0.50, "output": 25.00},
    "claude-opus-4.6": {"input": 5.00, "cached": 0.50, "output": 25.00},
    "claude-opus-4.7": {"input": 5.00, "cached": 0.50, "output": 25.00},
    "claude-opus-4.8": {"input": 5.00, "cached": 0.50, "output": 25.00},
    "claude-opus-5": {"input": 5.00, "cached": 0.50, "output": 25.00},
    # "Claude Opus 4.8 (fast mode)" - 2x the standard Opus rate. Both spellings
    # are listed so either telemetry form resolves exactly; the longest-key-first
    # matcher in `get_pricing` keeps these from being swallowed by "claude-opus-4.8".
    "claude-opus-4.8-fast": {"input": 10.00, "cached": 1.00, "output": 50.00},
    "claude-opus-4.8 (fast mode)": {"input": 10.00, "cached": 1.00, "output": 50.00},
    "claude-fable-5": {"input": 10.00, "cached": 1.00, "output": 50.00},
    # ---------------- OpenAI ----------------
    "gpt-5-mini": {"input": 0.25, "cached": 0.025, "output": 2.00},
    "gpt-5.3-codex": {"input": 1.75, "cached": 0.175, "output": 14.00},
    "gpt-5.4": {"input": 2.50, "cached": 0.25, "output": 15.00},
    "gpt-5.4-mini": {"input": 0.75, "cached": 0.075, "output": 4.50},
    "gpt-5.4-nano": {"input": 0.20, "cached": 0.02, "output": 1.25},
    "gpt-5.5": {"input": 5.00, "cached": 0.50, "output": 30.00},
    "gpt-5.6-luna": {"input": 0.20, "cached": 0.02, "output": 1.20},
    "gpt-5.6-terra": {"input": 2.00, "cached": 0.20, "output": 12.00},
    "gpt-5.6-sol": {"input": 5.00, "cached": 0.50, "output": 30.00},
    # ---------------- Google ----------------
    "gemini-3.1-pro": {"input": 2.00, "cached": 0.20, "output": 12.00},
    "gemini-3.5-flash": {"input": 1.50, "cached": 0.15, "output": 9.00},
    # Gemini 3.6/3.7 Flash carry promotional pricing through 2026-12-31; these
    # rates will rise when the promotion ends.
    "gemini-3.6-flash": {"input": 0.75, "cached": 0.075, "output": 3.75},
    "gemini-3.7-flash": {"input": 0.75, "cached": 0.075, "output": 3.75},
    # ---------------- GitHub (fine-tuned) ----------------
    "raptor-mini": {"input": 0.25, "cached": 0.025, "output": 2.00},
    # ---------------- Microsoft ----------------
    "mai-code-1-flash": {"input": 0.75, "cached": 0.075, "output": 4.50},
    "mai-code-1.1-flash": {"input": 0.20, "cached": 0.02, "output": 1.20},
    # ---------------- xAI ----------------
    # Note the unusually expensive cached-input rate (25% of input, not 10%).
    "grok-4.5": {"input": 2.00, "cached": 0.50, "output": 6.00},
    "grok-4.6": {"input": 2.00, "cached": 0.50, "output": 6.00},
    # ---------------- Moonshot AI ----------------
    "kimi-k2.7-code": {"input": 0.95, "cached": 0.19, "output": 4.00},
    "kimi-k3": {"input": 3.00, "cached": 0.30, "output": 15.00},
    # ---------------- Delisted ----------------
    # No longer on GitHub's model list or pricing table, kept only so historical
    # sessions that used them still price at the rate they were billed at. Do
    # not treat these as verifiable against the current docs.
    "gpt-4.1": {"input": 2.00, "cached": 0.50, "output": 8.00},
    "gpt-4o": {"input": 2.50, "cached": 1.25, "output": 10.00},
    "gpt-4o-mini-2024-07-18": {"input": 0.15, "cached": 0.075, "output": 0.60},
    "gpt-5.2": {"input": 1.75, "cached": 0.175, "output": 14.00},
    "gpt-5.2-codex": {"input": 1.75, "cached": 0.175, "output": 14.00},
    "gemini-2.5-pro": {"input": 1.25, "cached": 0.125, "output": 10.00},
    # Never appeared on an official pricing table (only 3.5/3.6/3.7 Flash do);
    # retained as a best-effort rate for any telemetry that names it.
    "gemini-3-flash": {"input": 0.50, "cached": 0.05, "output": 3.00},
}

# Officially documented cache-WRITE rates, USD per 1M tokens, for the models
# that have one (Anthropic: 1.25x input; GPT-5.6 family). Recorded here so the
# published number lives in the repo, but NOT applied by `calculate_cost` -
# see component (1) in the note above.
CACHE_WRITE_PRICING = {
    "claude-haiku-4.5": 1.25,
    "claude-sonnet-4": 3.75,
    "claude-sonnet-4.5": 3.75,
    "claude-sonnet-4.6": 3.75,
    "claude-sonnet-5": 2.50,
    "claude-opus-4.5": 6.25,
    "claude-opus-4.6": 6.25,
    "claude-opus-4.7": 6.25,
    "claude-opus-4.8": 6.25,
    "claude-opus-5": 6.25,
    "claude-opus-4.8-fast": 12.50,
    "claude-opus-4.8 (fast mode)": 12.50,
    "claude-fable-5": 12.50,
    "gpt-5.6-luna": 0.25,
    "gpt-5.6-terra": 2.50,
    "gpt-5.6-sol": 6.25,
}

# Applied when a model name matches nothing below. Sonnet-tier rates: the most
# common "versatile" tier on the official table, so an unknown model lands on a
# plausible middle estimate rather than the cheapest or most expensive row.
DEFAULT_PRICING = {"input": 3.00, "cached": 0.30, "output": 15.00}

READ_TOOLS = {"read_file"}


def match_keys(table) -> list[str]:
    """Model-name keys ordered longest-first for prefix/substring matching.

    Order matters and dict order does NOT work: telemetry emits suffixed names
    ("gpt-5.4-mini-2026-02-01", "claude-opus-4.8-fast"), and a shorter key that
    happens to be a prefix of a longer one would otherwise win purely because it
    was declared first - pricing `gpt-5.4-mini-*` as full `gpt-5.4` (3.3x too
    expensive) or `claude-opus-4.8-fast` as standard Opus (2x too cheap).
    Longest-first makes the most specific key win regardless of declaration order.
    """
    return sorted(table, key=len, reverse=True)


_PRICING_MATCH_KEYS = match_keys(PRICING)


def get_pricing(model_name: str | None) -> dict[str, float]:
    model_lower = (model_name or "").lower()
    if model_lower in PRICING:
        return PRICING[model_lower]
    for key in _PRICING_MATCH_KEYS:
        if model_lower.startswith(key) or key in model_lower:
            return PRICING[key]
    return dict(DEFAULT_PRICING)


def calculate_cost(input_tokens: float, output_tokens: float, cached_tokens: float, model_name: str | None) -> dict[str, float]:
    pricing = get_pricing(model_name)
    non_cached_input = max(0.0, float(input_tokens) - float(cached_tokens))
    cost_input = (non_cached_input / 1_000_000) * pricing["input"]
    cost_cached = (float(cached_tokens) / 1_000_000) * pricing["cached"]
    cost_output = (float(output_tokens) / 1_000_000) * pricing["output"]
    return {
        "input": float(input_tokens),
    "uncached": non_cached_input,
        "output": float(output_tokens),
        "cached": float(cached_tokens),
        "cost": cost_input + cost_cached + cost_output,
    }

