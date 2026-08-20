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

OVERHEAD_BUCKET_KEYS = (
    "system_prompt",
    "tool_definitions",
    "assistant_context",
    "user_messages",
    "tools",
    "files",
    "unattributed",
)


def new_token_block() -> dict[str, float]:
    return {"input": 0.0, "uncached": 0.0, "output": 0.0, "cached": 0.0, "cost": 0.0}


def new_overhead_buckets() -> dict[str, dict[str, float]]:
    return {key: new_token_block() for key in OVERHEAD_BUCKET_KEYS}


def add_token_block(target: dict[str, float], source: dict[str, float], scale: float = 1.0) -> None:
    for key in ("input", "uncached", "output", "cached", "cost"):
        target[key] = target.get(key, 0.0) + source.get(key, 0.0) * scale


def diff_counter(current: float | int, previous: float | int) -> float:
    current_value = float(current or 0)
    previous_value = float(previous or 0)
    if current_value < previous_value:
        return current_value
    return current_value - previous_value
