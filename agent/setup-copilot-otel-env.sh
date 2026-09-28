#!/usr/bin/env bash
# Sets the Copilot OTEL environment variables for macOS/Linux and merges
# Claude Code's OTEL export settings into ~/.claude/settings.json.
#
# Usage:
#   # Local Docker (default)
#   chmod +x setup-copilot-otel-env.sh
#   ./setup-copilot-otel-env.sh
#
#   # Remote server
#   ./setup-copilot-otel-env.sh remote
#
#   # Explicit local
#   ./setup-copilot-otel-env.sh local
#
# There is no macOS/Linux equivalent of install-openobserve-agent.ps1's
# Windows Scheduled Task (that part of the repo is Windows-only).

set -euo pipefail

# Parse mode argument (default: local)
MODE="${1:-local}"
MODE=$(echo "$MODE" | tr '[:upper:]' '[:lower:]')

if [ "$MODE" != "local" ] && [ "$MODE" != "remote" ]; then
  echo "Invalid mode: $MODE" >&2
  echo "Usage: $0 [local|remote]" >&2
  exit 1
fi

# ============================== CONFIG ==============================
# Configuration based on mode
# ======================================================================

if [ "$MODE" = "local" ]; then
  echo "*** MODE: LOCAL (Docker localhost) ***"
  OTEL_ENDPOINT_VALUE="http://localhost:4318"
  NEEDS_CERT=false
elif [ "$MODE" = "remote" ]; then
  echo "*** MODE: REMOTE (34.14.177.44) ***"
  OTEL_ENDPOINT_VALUE="https://34.14.177.44:8080"
  OPENOBSERVE_INSECURE_TLS_VALUE="true"
  NEEDS_CERT=true
fi

# Common settings
OTEL_SERVICE_NAME_VALUE="github-copilot"
OTEL_CAPTURE_MESSAGE_CONTENT_VALUE="true"
OTEL_PROTOCOL_VALUE="http/protobuf"
COPILOT_OTEL_EXPORTER_TYPES_VALUE="otlp-http"
COPILOT_OTEL_ENABLED_VALUE="true"
COPILOT_OTEL_CAPTURE_CONTENT_VALUE="true"

# --- Prompt for the values that vary per user/machine ---
echo
echo "Note: Resource attributes are set via environment variables in docker-compose.yaml for LOCAL mode."
echo "      This prompt is for the agent/collector attribution."
echo
read -r -p 'OTEL resource attributes (e.g. team.name=team1,department.name=dept1,user=YourName,org=AMS): ' OTEL_RESOURCE_ATTRIBUTES_VALUE
if [ -z "$OTEL_RESOURCE_ATTRIBUTES_VALUE" ]; then
  echo 'OTEL resource attributes are required.' >&2
  exit 1
fi

OTEL_CERTIFICATE_PATH_VALUE=""
if [ "$NEEDS_CERT" = true ]; then
  read -r -p 'Path to OTEL exporter certificate (ca.crt): ' OTEL_CERTIFICATE_PATH_VALUE
  if [ -z "$OTEL_CERTIFICATE_PATH_VALUE" ]; then
    echo 'OTEL certificate path is required for REMOTE mode.' >&2
    exit 1
  fi
  if [ ! -f "$OTEL_CERTIFICATE_PATH_VALUE" ]; then
    echo "Warning: certificate not found at '$OTEL_CERTIFICATE_PATH_VALUE' -- continuing anyway, but the OTEL exporter will fail until it exists." >&2
  fi
else
  echo "Skipping certificate prompt: LOCAL mode uses http:// (no TLS, no cert needed)."
fi

# Pick the shell profile that will actually get sourced for new terminals.
PROFILE_FILE="$HOME/.zshrc"
if [ -n "${BASH_VERSION:-}" ] && [ -f "$HOME/.bash_profile" ]; then
  PROFILE_FILE="$HOME/.bash_profile"
fi

MARKER_START="# >>> copilot-otel-agent env (managed) >>>"
MARKER_END="# <<< copilot-otel-agent env (managed) <<<"

# Remove any previously-written block so re-running this script updates in place.
if [ -f "$PROFILE_FILE" ] && grep -qF "$MARKER_START" "$PROFILE_FILE"; then
  sed -i.bak "/$MARKER_START/,/$MARKER_END/d" "$PROFILE_FILE"
fi

{
  echo "$MARKER_START"
  echo "export OTEL_RESOURCE_ATTRIBUTES=\"$OTEL_RESOURCE_ATTRIBUTES_VALUE\""
  echo "export OTEL_SERVICE_NAME=\"$OTEL_SERVICE_NAME_VALUE\""
  echo "export OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=\"$OTEL_CAPTURE_MESSAGE_CONTENT_VALUE\""
  echo "export OTEL_EXPORTER_OTLP_PROTOCOL=\"$OTEL_PROTOCOL_VALUE\""
  echo "export OTEL_EXPORTER_OTLP_ENDPOINT=\"$OTEL_ENDPOINT_VALUE\""
  if [ "$NEEDS_CERT" = true ]; then
    echo "export OPENOBSERVE_INSECURE_TLS=\"$OPENOBSERVE_INSECURE_TLS_VALUE\""
    echo "export OTEL_EXPORTER_OTLP_CERTIFICATE=\"$OTEL_CERTIFICATE_PATH_VALUE\""
  fi
  echo "export COPILOT_OTEL_EXPORTER_TYPES=\"$COPILOT_OTEL_EXPORTER_TYPES_VALUE\""
  echo "export COPILOT_OTEL_ENABLED=\"$COPILOT_OTEL_ENABLED_VALUE\""
  echo "export COPILOT_OTEL_CAPTURE_CONTENT=\"$COPILOT_OTEL_CAPTURE_CONTENT_VALUE\""
  echo "$MARKER_END"
} >> "$PROFILE_FILE"

# Also export into the current shell so it takes effect immediately, without a new terminal.
export OTEL_RESOURCE_ATTRIBUTES="$OTEL_RESOURCE_ATTRIBUTES_VALUE"
export OTEL_SERVICE_NAME="$OTEL_SERVICE_NAME_VALUE"
export OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT="$OTEL_CAPTURE_MESSAGE_CONTENT_VALUE"
export OTEL_EXPORTER_OTLP_PROTOCOL="$OTEL_PROTOCOL_VALUE"
export OTEL_EXPORTER_OTLP_ENDPOINT="$OTEL_ENDPOINT_VALUE"
if [ "$NEEDS_CERT" = true ]; then
  export OPENOBSERVE_INSECURE_TLS="$OPENOBSERVE_INSECURE_TLS_VALUE"
  export OTEL_EXPORTER_OTLP_CERTIFICATE="$OTEL_CERTIFICATE_PATH_VALUE"
else
  # Clear stale TLS settings left over from a previous REMOTE run in this same shell session --
  # otherwise switching back to LOCAL keeps pointing OTEL at a certificate it no longer needs.
  unset OPENOBSERVE_INSECURE_TLS OTEL_EXPORTER_OTLP_CERTIFICATE 2>/dev/null || true
fi
export COPILOT_OTEL_EXPORTER_TYPES="$COPILOT_OTEL_EXPORTER_TYPES_VALUE"
export COPILOT_OTEL_ENABLED="$COPILOT_OTEL_ENABLED_VALUE"
export COPILOT_OTEL_CAPTURE_CONTENT="$COPILOT_OTEL_CAPTURE_CONTENT_VALUE"

# --- Claude Code: merge its OTEL export settings into ~/.claude/settings.json ---
# Same keys Setup-CopilotOtelAgent.ps1 writes on Windows. Other settings in the file are kept.
# Reference: https://openobserve.ai/docs/integration/ai/claude-code-tracing/
if [ "$MODE" = "local" ]; then
  CLAUDE_OTEL_ENDPOINT_VALUE="http://localhost:4418"
else
  CLAUDE_OTEL_ENDPOINT_VALUE="https://34.14.177.44:8080"
fi
OPENOBSERVE_USER_NAME="admin@localhost.dev"

OPENOBSERVE_PASSWORD_VALUE=""
if [ "$NEEDS_CERT" = true ]; then
  read -r -s -p "OpenObserve password for '$OPENOBSERVE_USER_NAME': " OPENOBSERVE_PASSWORD_VALUE
  echo
  if [ -z "$OPENOBSERVE_PASSWORD_VALUE" ]; then
    echo 'OpenObserve password is required for REMOTE mode.' >&2
    exit 1
  fi
fi

PYTHON_BIN="$(command -v python3 || command -v python || true)"
if [ -z "$PYTHON_BIN" ]; then
  echo 'python3 was not found on PATH -- it is needed to update ~/.claude/settings.json.' >&2
  exit 1
fi

# Values go through the environment (not argv) so the password never shows up in `ps`.
CLAUDE_ENDPOINT="$CLAUDE_OTEL_ENDPOINT_VALUE" \
CLAUDE_PROTOCOL="$OTEL_PROTOCOL_VALUE" \
CLAUDE_ATTRS="$OTEL_RESOURCE_ATTRIBUTES_VALUE" \
CLAUDE_CERT="$OTEL_CERTIFICATE_PATH_VALUE" \
CLAUDE_USER="$OPENOBSERVE_USER_NAME" \
CLAUDE_PASSWORD="$OPENOBSERVE_PASSWORD_VALUE" \
"$PYTHON_BIN" - <<'PY'
import base64, json, os, pathlib

path = pathlib.Path.home() / ".claude" / "settings.json"
path.parent.mkdir(parents=True, exist_ok=True)
settings = json.loads(path.read_text(encoding="utf-8")) if path.exists() and path.read_text(encoding="utf-8").strip() else {}
env = settings.setdefault("env", {})

env.update({
    "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
    "OTEL_METRICS_EXPORTER": "otlp",
    "OTEL_LOGS_EXPORTER": "otlp",
    "OTEL_TRACES_EXPORTER": "otlp",
    "CLAUDE_CODE_ENHANCED_TELEMETRY_BETA": "1",
    "OTEL_EXPORTER_OTLP_PROTOCOL": os.environ["CLAUDE_PROTOCOL"],
    "OTEL_EXPORTER_OTLP_ENDPOINT": os.environ["CLAUDE_ENDPOINT"],
    "OTEL_SERVICE_NAME": "claude-code",
    "OTEL_RESOURCE_ATTRIBUTES": os.environ["CLAUDE_ATTRS"],
    "OTEL_LOG_USER_PROMPTS": "1",
    "OTEL_LOG_ASSISTANT_RESPONSES": "1",
})

if os.environ["CLAUDE_ENDPOINT"].startswith("https://"):
    token = base64.b64encode(f'{os.environ["CLAUDE_USER"]}:{os.environ["CLAUDE_PASSWORD"]}'.encode()).decode()
    env["OTEL_EXPORTER_OTLP_HEADERS"] = f"Authorization=Basic {token},stream-name=claude-code"
    env["OTEL_EXPORTER_OTLP_CERTIFICATE"] = os.environ["CLAUDE_CERT"]
    env["NODE_EXTRA_CA_CERTS"] = os.environ["CLAUDE_CERT"]
else:
    # Clear stale TLS/auth settings left over from a previous REMOTE run.
    for key in ("OTEL_EXPORTER_OTLP_HEADERS", "OTEL_EXPORTER_OTLP_CERTIFICATE", "NODE_EXTRA_CA_CERTS"):
        env.pop(key, None)

path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
PY
unset OPENOBSERVE_PASSWORD_VALUE
echo "✓ Merged Claude Code OTEL config into $HOME/.claude/settings.json (other settings in that file are preserved)."

echo
echo "✓ Wrote OTEL/Copilot env vars to $PROFILE_FILE and exported them into this shell."
echo "✓ Open a new terminal (or run 'source $PROFILE_FILE') for other terminals/apps to see them."
echo
echo "Configuration:"
echo "  Mode: $MODE"
echo "  Endpoint: $OTEL_ENDPOINT_VALUE"
if [ "$NEEDS_CERT" = true ]; then
  echo "  Certificate: $OTEL_CERTIFICATE_PATH_VALUE"
else
  echo "  Certificate: Not required (HTTP mode)"
fi
echo
echo "Note: install-openobserve-agent.ps1's recurring scheduled task (Step 3) is Windows-only."
echo "On macOS/Linux, run the equivalent python commands by hand or wire them into cron/launchd."
echo
if [ "$MODE" = "local" ]; then
  echo "For LOCAL mode, make sure Docker is running:"
  echo "  cd <observability-dir> && docker compose up -d"
  echo
  echo "Access OpenObserve at: http://localhost:5080"
  echo "  Username: admin@localhost.dev"
  echo "  Password: OpenObserve1!"
else
  echo "For REMOTE mode, access OpenObserve at: https://34.14.177.44"
  echo "  Username: admin@localhost.dev"
  echo "  Password: <your-server-password>"
fi
echo
echo "To switch modes later, re-run: $0 [local|remote]"
