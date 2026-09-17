#!/usr/bin/env bash
# Sets the Copilot:8080 environment variables for macOS/Linux and (optionally)
# installs a cron job that periodically regenerates the dashboard + pushes to
# OpenObserve, using the same python scripts the Windows agent calls.
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
# Windows Scheduled Task (that part of the repo is Windows-only). This script
# covers Step 1 (OTEL env vars) and offers an optional cron-based Step 3
# using generate_dashboard.py / openobserve_export.py / chronicle_export.py
# directly, since those are plain python and cross-platform.

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
