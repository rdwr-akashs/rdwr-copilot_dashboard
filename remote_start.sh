#!/bin/bash
set -euo pipefail

export COPILOT_DASHBOARD_CACHE_VERIFY_SECONDS="${COPILOT_DASHBOARD_CACHE_VERIFY_SECONDS:-30}"
export COPILOT_DASHBOARD_CACHE_POLL_SECONDS="${COPILOT_DASHBOARD_CACHE_POLL_SECONDS:-30}"

if [[ -n "${1:-}" ]]; then
  export COPILOT_DASHBOARD_CACHE_SHARD="$1"
  shift
fi

exec python3 serve_dashboard.py --cache-only --workers 64 --cache-poll-seconds "$COPILOT_DASHBOARD_CACHE_POLL_SECONDS" "$@"