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

# GitHub Copilot pricing per 1M tokens (June 2026 pricing tables).
# Current Copilot debug telemetry exposes per-call input / output / cached-read
# counters. This dashboard treats `inputTokens` as the billed input for the
# call, with `cachedTokens` as its cached-read subset. Current debug logs do not
# expose explicit cache-write counts, so costs below reflect observed telemetry
# only.
PRICING = {
    # Anthropic
    "claude-haiku-4.5": {"input": 1.00, "cached": 0.10, "output": 5.00},
    "claude-sonnet-4": {"input": 3.00, "cached": 0.30, "output": 15.00},
    "claude-sonnet-4.5": {"input": 3.00, "cached": 0.30, "output": 15.00},
    "claude-sonnet-4.6": {"input": 3.00, "cached": 0.30, "output": 15.00},
    "claude-sonnet-5": {"input": 2.00, "cached": 0.20, "output": 10.00},
    "claude-opus-4.5": {"input": 5.00, "cached": 0.50, "output": 25.00},
    "claude-opus-4.6": {"input": 5.00, "cached": 0.50, "output": 25.00},
    "claude-opus-4.7": {"input": 5.00, "cached": 0.50, "output": 25.00},
    "claude-opus-4.8": {"input": 5.00, "cached": 0.50, "output": 25.00},
    # OpenAI
    "gpt-4.1": {"input": 2.00, "cached": 0.50, "output": 8.00},
    "gpt-5-mini": {"input": 0.25, "cached": 0.025, "output": 2.00},
    "gpt-5.2": {"input": 1.75, "cached": 0.175, "output": 14.00},
    "gpt-5.2-codex": {"input": 1.75, "cached": 0.175, "output": 14.00},
    "gpt-5.3-codex": {"input": 1.75, "cached": 0.175, "output": 14.00},
    "gpt-5.4": {"input": 2.50, "cached": 0.25, "output": 15.00},
    "gpt-5.4-mini": {"input": 0.75, "cached": 0.075, "output": 4.50},
    "gpt-5.4-nano": {"input": 0.20, "cached": 0.02, "output": 1.25},
    "gpt-5.5": {"input": 5.00, "cached": 0.50, "output": 30.00},
    "gpt-4o-mini-2024-07-18": {"input": 0.15, "cached": 0.075, "output": 0.60},
    "gpt-4o": {"input": 2.50, "cached": 1.25, "output": 10.00},
    "gpt-5.6-luna": {"input": 1.00, "cached": 0.10, "output": 6.00},
    "gpt-5.6-terra": {"input": 2.50, "cached": 0.25, "output": 15.00},
    "gpt-5.6-sol": {"input": 5.00, "cached": 0.50, "output": 30.00},
    # Google
    "gemini-2.5-pro": {"input": 1.25, "cached": 0.125, "output": 10.00},
    "gemini-3-flash": {"input": 0.50, "cached": 0.05, "output": 3.00},
    "gemini-3.1-pro": {"input": 2.00, "cached": 0.20, "output": 12.00},
    "gemini-3.5-flash": {"input": 1.50, "cached": 0.15, "output": 9.00},
}

READ_TOOLS = {"read_file"}

def get_pricing(model_name: str | None) -> dict[str, float]:
    model_lower = (model_name or "").lower()
    if model_lower in PRICING:
        return PRICING[model_lower]
    for key, pricing in PRICING.items():
        if model_lower.startswith(key) or key in model_lower:
            return pricing
    return {"input": 3.00, "cached": 0.30, "output": 15.00}


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

