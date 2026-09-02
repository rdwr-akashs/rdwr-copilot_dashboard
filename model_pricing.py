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
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import fcntl  # type: ignore
except Exception:  # pragma: no cover - non-Linux platforms
    fcntl = None

from dashboard_utils import *

import diagnostics

import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# GitHub Copilot model prices, USD per 1M tokens.
#
# SOURCE OF TRUTH: https://docs.github.com/en/copilot/reference/copilot-billing/models-and-pricing
# (the "Pricing tables" section). Verified against that page on 2026-08-24;
# every value in the "current" block below is quoted from it verbatim. GitHub
# bills Copilot usage in AI credits, where 1 credit = $0.01 USD, priced off
# these same per-token rates (see premium_requests.py), so a dollar figure here
# is 100x the credit figure GitHub charges.
#
# THIS TABLE IS THE FALLBACK, NOT THE PRIMARY COST SOURCE. The Copilot CLI's
# session-store.db records what GitHub actually billed per call
# (`total_nano_aiu`, plus the per-token-type rates it applied in
# `token_details_json`), so CLI costs are read from that and are exact - see
# `cli_usage.py`. This table prices the VS Code chat half of the data, where no
# billing figure is exposed, and backstops CLI rows that predate those columns.
#
# What the table can and cannot model when used as that fallback:
#
#   1. Cache writes ARE priced, from CACHE_WRITE_PRICING below, whenever the
#      caller can supply a cache-write token count (the CLI can; VS Code chat
#      telemetry exposes no cache-write counter, so chat costs remain a lower
#      bound for cache-heavy sessions).
#   2. Long-context tiers ARE priced, from LONG_CONTEXT_PRICING below, whenever
#      the caller supplies the call's prompt size. Both sources record
#      per-call input tokens, so this applies to chat and CLI alike.
#   3. The 10% discount on model costs when using auto model selection is NOT
#      modelled - nothing in either source flags a call as auto-routed. It
#      makes fallback estimates up to 10% high on auto-routed calls. Costs read
#      from `total_nano_aiu` / `token_details_json` already have it applied.
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
    # GPT-5.6 Sol carries promotional pricing through 2026-09-03; these rates
    # will rise when the promotion ends.
    "gpt-5.6-sol": {"input": 2.00, "cached": 0.20, "output": 10.00},
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
# that have one (Anthropic: 1.25x input; GPT-5.6 family). Every other model
# prints "Not applicable" on the pricing page and is billed 0 for cache
# writes - hence `cache_write_rate()` returning 0.0 for an absent key rather
# than falling back to a multiple of the input rate.
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
    "gpt-5.6-sol": 2.50,
}

# Long-context tiers, quoted from the same pricing page. Above `threshold`
# prompt tokens the whole call is billed at these rates instead of the default
# ones in PRICING/CACHE_WRITE_PRICING. Models absent from this dict have a
# single tier at any prompt size.
#
# `cacheWrite` is only present where the page prints one; where it is absent
# the model bills nothing for cache writes at either tier.
LONG_CONTEXT_PRICING = {
    "gpt-5.4": {"threshold": 272_000, "input": 5.00, "cached": 0.50, "output": 22.50},
    "gpt-5.5": {"threshold": 272_000, "input": 10.00, "cached": 1.00, "output": 45.00},
    "gpt-5.6-luna": {"threshold": 200_000, "input": 0.40, "cached": 0.04, "cacheWrite": 0.50, "output": 1.80},
    "gpt-5.6-sol": {"threshold": 272_000, "input": 4.00, "cached": 0.40, "cacheWrite": 5.00, "output": 15.00},
    "gpt-5.6-terra": {"threshold": 272_000, "input": 4.00, "cached": 0.40, "cacheWrite": 5.00, "output": 18.00},
    "gemini-3.1-pro": {"threshold": 200_000, "input": 4.00, "cached": 0.40, "output": 18.00},
    "grok-4.5": {"threshold": 200_000, "input": 4.00, "cached": 1.00, "output": 12.00},
    "grok-4.6": {"threshold": 200_000, "input": 4.00, "cached": 1.00, "output": 12.00},
}

# GitHub meters Copilot model usage in AI credits: 1 credit (1 "AIU") = $0.01.
# The CLI's session-store.db records per-call spend in *nano* AIU, so one
# nano-AIU is $1e-11. Verified numerically against `token_details_json`: for
# every sampled call, sum(tokenCount / batchSize * costPerBatch) equals
# `total_nano_aiu` exactly, and the implied per-1M rates match the published
# pricing table above to the cent.
AIU_USD = 0.01
NANO_AIU_PER_AIU = 1_000_000_000
NANO_AIU_USD = AIU_USD / NANO_AIU_PER_AIU  # 1e-11

ENV_PRICING_API_URL = "COPILOT_PRICING_API_URL"
ENV_PRICING_CACHE_PATH = "COPILOT_PRICING_CACHE_PATH"
ENV_PRICING_CACHE_DAYS = "COPILOT_PRICING_CACHE_DAYS"
# A centrally hosted pricing-service endpoint lets each developer machine
# refresh frequently while the last valid cache remains available offline.
DEFAULT_PRICING_CACHE_DAYS = 1 / 24


def pricing_cache_path() -> str:
    configured = os.environ.get(ENV_PRICING_CACHE_PATH)
    if configured:
        return os.path.abspath(os.path.expanduser(configured))
    return os.path.join(os.path.expanduser("~"), ".copilot-dashboard", "model_pricing.json")


def _pricing_cache_is_fresh(path: str, refresh_days: int) -> bool:
    try:
        return time.time() - os.path.getmtime(path) < refresh_days * 86_400
    except OSError:
        return False


def _read_pricing_document(path: str) -> dict[str, Any] | None:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, ValueError):
        return None
    pricing = document.get("pricing") if isinstance(document, dict) else None
    return document if isinstance(pricing, dict) else None


def _apply_pricing_document(document: dict[str, Any]) -> bool:
    pricing = document.get("pricing")
    if not isinstance(pricing, dict) or not pricing:
        return False
    normalized: dict[str, dict[str, float]] = {}
    for model, rates in pricing.items():
        if not isinstance(model, str) or not isinstance(rates, dict):
            return False
        try:
            normalized[model.lower()] = {
                "input": float(rates["input"]),
                "cached": float(rates["cached"]),
                "output": float(rates["output"]),
            }
        except (KeyError, TypeError, ValueError):
            return False
    PRICING.update(normalized)
    cache_write = document.get("cacheWritePricing")
    if isinstance(cache_write, dict):
        CACHE_WRITE_PRICING.update({str(name).lower(): float(rate) for name, rate in cache_write.items()})
    long_context = document.get("longContextPricing")
    if isinstance(long_context, dict):
        LONG_CONTEXT_PRICING.update({str(name).lower(): dict(rate) for name, rate in long_context.items() if isinstance(rate, dict)})
    _refresh_pricing_match_keys()
    return True


def _refresh_pricing_match_keys() -> None:
    global _PRICING_MATCH_KEYS, _CACHE_WRITE_MATCH_KEYS, _LONG_CONTEXT_MATCH_KEYS
    _PRICING_MATCH_KEYS = match_keys(PRICING)
    _CACHE_WRITE_MATCH_KEYS = match_keys(CACHE_WRITE_PRICING)
    _LONG_CONTEXT_MATCH_KEYS = match_keys(LONG_CONTEXT_PRICING)


def load_cached_pricing() -> bool:
    """Apply a previously validated pricing API response without network access."""
    document = _read_pricing_document(pricing_cache_path())
    return bool(document and _apply_pricing_document(document))


def refresh_pricing_from_api(force: bool = False, timeout: float = 10.0) -> bool:
    """Refresh cached pricing from `COPILOT_PRICING_API_URL` when it is stale.

    The endpoint must return JSON with a required `pricing` object, where each
    model has numeric `input`, `cached`, and `output` USD-per-million rates.
    Optional `cacheWritePricing` and `longContextPricing` objects use this
    module's existing table shapes. An invalid/unavailable response leaves the
    existing cache and embedded fallback untouched.
    """
    url = os.environ.get(ENV_PRICING_API_URL)
    if not url:
        return load_cached_pricing()
    try:
        refresh_days = max(1 / 24, float(os.environ.get(ENV_PRICING_CACHE_DAYS, DEFAULT_PRICING_CACHE_DAYS)))
    except ValueError:
        refresh_days = DEFAULT_PRICING_CACHE_DAYS
    path = pricing_cache_path()
    if not force and _pricing_cache_is_fresh(path, refresh_days):
        return load_cached_pricing()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            document = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError):
        return load_cached_pricing()
    if not isinstance(document, dict) or not _apply_pricing_document(document):
        return load_cached_pricing()
    try:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        temporary = f"{path}.{os.getpid()}.tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(document, handle, sort_keys=True)
        os.replace(temporary, path)
    except OSError:
        pass
    return True

# The billed token categories GitHub prices separately, in the order they are
# reported. `cache_read`/`cache_write` are the wire names used by the CLI's
# `token_details_json`; `input` there means the *uncached* remainder of the
# prompt, NOT the whole prompt.
TOKEN_TYPES = ("input", "cache_read", "cache_write", "output")

# Maps a billed token category to its key in a PRICING / LONG_CONTEXT_PRICING row.
_RATE_KEY_FOR_TOKEN_TYPE = {
    "input": "input",
    "cache_read": "cached",
    "cache_write": "cacheWrite",
    "output": "output",
}


def nano_aiu_to_usd(nano_aiu: float | int | None) -> float:
    """Convert GitHub's billed nano-AI-units into USD (1 nano AIU = $1e-11)."""
    return float(nano_aiu or 0.0) * NANO_AIU_USD


def usd_to_nano_aiu(usd: float | None) -> float:
    """Convert USD back into nano AI units."""
    return float(usd or 0.0) / NANO_AIU_USD

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
_CACHE_WRITE_MATCH_KEYS = match_keys(CACHE_WRITE_PRICING)
_LONG_CONTEXT_MATCH_KEYS = match_keys(LONG_CONTEXT_PRICING)

# Network refresh is opt-in through COPILOT_PRICING_API_URL; a valid local cache
# is always safe to apply during import.
load_cached_pricing()


def _match(model_name: str | None, table, keys) -> Any | None:
    """Longest-key-first lookup of `model_name` in one of the rate tables."""
    model_lower = (model_name or "").lower()
    if model_lower in table:
        return table[model_lower]
    for key in keys:
        if model_lower.startswith(key) or key in model_lower:
            return table[key]
    return None


def get_pricing(model_name: str | None) -> dict[str, float]:
    matched = _match(model_name, PRICING, _PRICING_MATCH_KEYS)
    return matched if matched is not None else dict(DEFAULT_PRICING)


def cache_write_rate(model_name: str | None) -> float:
    """Published cache-write rate (USD per 1M tokens), or 0.0 if unpriced.

    Models whose pricing row prints "Not applicable" for cache write are billed
    nothing for those tokens, so 0.0 is the correct rate - not a guess.
    """
    matched = _match(model_name, CACHE_WRITE_PRICING, _CACHE_WRITE_MATCH_KEYS)
    return float(matched) if matched is not None else 0.0


def get_rates(model_name: str | None, prompt_tokens: float | None = None) -> dict[str, Any]:
    """Resolve the four billed per-1M rates for a call, long-context tier included.

    `prompt_tokens` is the call's total prompt size (cached + uncached + cache
    writes), which is what GitHub compares against a model's long-context
    threshold. Pass None when the caller does not know it; the default tier is
    then used, exactly as before.

    Returns {"input", "cache_read", "cache_write", "output", "tier"} where the
    rate values are USD per 1M tokens.
    """
    default = get_pricing(model_name)
    rates = {
        "input": float(default["input"]),
        "cache_read": float(default["cached"]),
        "cache_write": cache_write_rate(model_name),
        "output": float(default["output"]),
        "tier": "default",
    }

    tier = _match(model_name, LONG_CONTEXT_PRICING, _LONG_CONTEXT_MATCH_KEYS)
    if tier and prompt_tokens is not None and float(prompt_tokens) > float(tier["threshold"]):
        rates["input"] = float(tier["input"])
        rates["cache_read"] = float(tier["cached"])
        rates["output"] = float(tier["output"])
        # Absent `cacheWrite` on a long-context row means the model does not
        # price cache writes at all, so keep the (zero) default-tier rate.
        if "cacheWrite" in tier:
            rates["cache_write"] = float(tier["cacheWrite"])
        rates["tier"] = "long"

    return rates


def cost_from_token_counts(
    counts: dict[str, float],
    model_name: str | None,
    prompt_tokens: float | None = None,
    rates: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Price already-split billed token counts, one entry per TOKEN_TYPES key.

    `counts` uses GitHub's own categories, so `counts["input"]` is the
    *uncached* prompt remainder - never the whole prompt. Callers holding an
    all-inclusive prompt counter should use `split_prompt_tokens()` first.

    `rates` overrides the published table when the caller knows the exact rates
    GitHub applied to this call (the CLI reads them out of
    `token_details_json`), which is what makes a priced-from-rates cost exact
    rather than an estimate.

    Returns {"cost", "byType": {type: usd}, "rates", "tier"}.
    """
    resolved = dict(rates) if rates else get_rates(model_name, prompt_tokens)
    by_type = {}
    total = 0.0
    for token_type in TOKEN_TYPES:
        tokens = max(0.0, float(counts.get(token_type) or 0.0))
        usd = (tokens / 1_000_000.0) * float(resolved.get(token_type) or 0.0)
        by_type[token_type] = usd
        total += usd
    return {
        "cost": total,
        "byType": by_type,
        "rates": {k: float(resolved.get(k) or 0.0) for k in TOKEN_TYPES},
        "tier": resolved.get("tier", "default"),
    }


def prompt_split_overflow(prompt_tokens: float, cache_read_tokens: float, cache_write_tokens: float) -> float:
    """How many cache tokens a call claims *beyond* its own reported prompt size.

    Zero on healthy telemetry. Anything above zero means the source contradicted
    itself (see `split_prompt_tokens` on why the prompt counter is
    all-inclusive), so the categories cannot all be billed as reported.
    """
    prompt = max(0.0, float(prompt_tokens or 0.0))
    cache_read = max(0.0, float(cache_read_tokens or 0.0))
    cache_write = max(0.0, float(cache_write_tokens or 0.0))
    return max(0.0, cache_read + cache_write - prompt)


def split_prompt_tokens(prompt_tokens: float, cache_read_tokens: float, cache_write_tokens: float) -> dict[str, float]:
    """Split an all-inclusive prompt counter into GitHub's billed categories.

    Both data sources report a single prompt total (`input_tokens` in the CLI
    DB, `inputTokens` in chat telemetry) that *contains* the cache-read and
    cache-write tokens - verified against the CLI DB, where
    `input_tokens == input + cache_read + cache_write` from
    `token_details_json` on every row. Charging the whole prompt at the input
    rate on top of the cache lines would double-bill it; charging
    `prompt - cache_read` at the input rate (what this repo used to do) bills
    cache writes at the input rate instead of the higher cache-write rate.

    The split is therefore a PARTITION of the prompt, and it is enforced as one:
    `cache_read + cache_write` is clamped so the three categories can never sum
    past the reported prompt size. Without the clamp, telemetry that reports
    more cached tokens than prompt tokens (which happens - a cache counter read
    from a different call than the prompt counter) prices those extra tokens on
    top of a prompt that never contained them, inflating the cost of the very
    calls whose counters are least trustworthy. Clamping in reporting order
    (cache reads first, then whatever prompt is left for cache writes) keeps the
    cheaper, more reliably reported category intact and drops the excess from
    the expensive one. `prompt_split_overflow()` reports how much was dropped so
    a caller can surface it rather than silently absorb it.
    """
    prompt = max(0.0, float(prompt_tokens or 0.0))
    cache_read = min(max(0.0, float(cache_read_tokens or 0.0)), prompt)
    cache_write = min(max(0.0, float(cache_write_tokens or 0.0)), prompt - cache_read)
    return {
        "input": max(0.0, prompt - cache_read - cache_write),
        "cache_read": cache_read,
        "cache_write": cache_write,
    }


def calculate_cost(
    input_tokens: float,
    output_tokens: float,
    cached_tokens: float,
    model_name: str | None,
    cache_write_tokens: float = 0.0,
    rates: dict[str, float] | None = None,
    tier_prompt_tokens: float | None = None,
) -> dict[str, float]:
    """Price one call (or one aggregated bucket) from published rates.

    `input_tokens` is the all-inclusive prompt counter both sources report, so
    the cache-read and cache-write tokens are carved out of it rather than
    charged on top - see `split_prompt_tokens`. It also selects the
    long-context tier where the model has one.

    `cache_write_tokens` defaults to 0 because VS Code chat telemetry has no
    such counter; the CLI passes its real value.

    `rates` lets a caller substitute the exact rates GitHub billed at instead
    of the published table.

    `tier_prompt_tokens` separates "how many tokens am I pricing" from "how big
    was the call GitHub priced". They differ whenever a caller prices a SUBSET
    of a call's tokens - the chat pipeline's prompt-growth attribution prices
    only the net-new tokens of each turn (see `per_chat_calculations.py`). The
    long-context tier is a property of the whole call: GitHub bills every token
    of a 300k-token prompt at the long-context rates, including the 5k that
    happen to be new this turn. Leaving this None on such a caller would price
    those tokens at the default tier and understate the call by the full
    tier delta (for gpt-5.4, input 2.50 -> 5.00 and output 15.00 -> 22.50).
    Defaults to `input_tokens`, which is correct for any caller pricing a whole
    call.

    Keeps its original return keys - `uncached` still means "prompt tokens
    billed at the full input rate" - and adds `cacheWrite`, `costByType`,
    `tier`, and `rates`.
    """
    overflow = prompt_split_overflow(input_tokens, cached_tokens, cache_write_tokens)
    if overflow > 0:
        # Not cosmetic: the clamp in `split_prompt_tokens` changed what got
        # billed, so the figure differs from a naive reading of the raw
        # counters. Reported per model so one broken model's telemetry is
        # visible without drowning the list.
        diagnostics.report(
            diagnostics.CODE_PRICING_PROMPT_OVERFLOW,
            (
                "Telemetry reported more cached/cache-write tokens than prompt tokens for "
                f"{model_name or 'unknown'}; the excess ({overflow:,.0f} tokens on at least one call) "
                "is not billed, because the prompt counter is all-inclusive. Cost for these calls is "
                "capped at pricing their whole reported prompt."
            ),
            severity="warning",
            impact="cost",
            source=str(model_name or "unknown"),
        )

    counts = split_prompt_tokens(input_tokens, cached_tokens, cache_write_tokens)
    priced = cost_from_token_counts(
        {**counts, "output": float(output_tokens or 0.0)},
        model_name,
        prompt_tokens=float((tier_prompt_tokens if tier_prompt_tokens is not None else input_tokens) or 0.0),
        rates=rates,
    )
    return {
        "input": float(input_tokens),
        "uncached": counts["input"],
        "output": float(output_tokens),
        "cached": counts["cache_read"],
        "cacheWrite": counts["cache_write"],
        "cost": priced["cost"],
        "costByType": priced["byType"],
        "rates": priced["rates"],
        "tier": priced["tier"],
    }

