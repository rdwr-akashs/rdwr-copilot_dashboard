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

def make_model_bucket() -> dict[str, Any]:
    return {
        "count": 0,
        "duration_ms": 0.0,
        "ttft_ms": 0.0,
        "input": 0.0,
    "uncached": 0.0,
        "output": 0.0,
        "cached": 0.0,
        "cost": 0.0,
        "session_ids": set(),
    }


def make_tool_bucket() -> dict[str, Any]:
    return {
        "count": 0,
        "duration_ms": 0.0,
        "errors": 0,
        "payload_tokens_estimate": 0.0,
        "input": 0.0,
    "uncached": 0.0,
        "output": 0.0,
        "cached": 0.0,
        "cost": 0.0,
        "session_ids": set(),
        "mode": "other",
    }


def make_file_bucket(path: str) -> dict[str, Any]:
    return {
        "path": path,
        "read_count": 0,
        "edit_count": 0,
        "payload_tokens_estimate": 0.0,
        "input": 0.0,
    "uncached": 0.0,
        "output": 0.0,
        "cached": 0.0,
        "cost": 0.0,
        "tools": set(),
        "session_ids": set(),
    "tool_usage": {},
    "tool_reference_count": 0,
    }


def make_file_tool_usage_bucket(tool_name: str, mode: str) -> dict[str, Any]:
  bucket = new_token_block()
  bucket.update(
    {
      "name": tool_name,
      "mode": mode,
      "count": 0,
      "duration_ms": 0.0,
      "payload_tokens_estimate": 0.0,
      "session_ids": set(),
    }
  )
  return bucket


def ensure_model_bucket(analysis: dict[str, Any], model_name: str) -> dict[str, Any]:
    bucket = analysis["models"].get(model_name)
    if bucket is None:
        bucket = make_model_bucket()
        analysis["models"][model_name] = bucket
    return bucket


def ensure_tool_bucket(analysis: dict[str, Any], tool_name: str, mode: str = "other") -> dict[str, Any]:
    bucket = analysis["tools"].get(tool_name)
    if bucket is None:
        bucket = make_tool_bucket()
        analysis["tools"][tool_name] = bucket
    if bucket["mode"] == "other" and mode != "other":
        bucket["mode"] = mode
    return bucket


def ensure_file_bucket(analysis: dict[str, Any], path: str) -> dict[str, Any]:
    bucket = analysis["files"].get(path)
    if bucket is None:
        bucket = make_file_bucket(path)
        analysis["files"][path] = bucket
    return bucket

