#!/usr/bin/env bash
# Sets the Copilot/OTEL environment variables for macOS/Linux and (optionally)
# installs a cron job that periodically regenerates the dashboard + pushes to
# OpenObserve, using the same python scripts the Windows agent calls.
#
# Usage:
#   chmod +x setup-copilot-otel-env.sh
#   ./setup-copilot-otel-env.sh
#
# There is no macOS/Linux equivalent of install-openobserve-agent.ps1's
# Windows Scheduled Task (that part of the repo is Windows-only). This script
# covers Step 1 (OTEL env vars) and offers an optional cron-based Step 3
# using generate_dashboard.py / openobserve_export.py / chronicle_export.py
# directly, since those are plain python and cross-platform.

set -euo pipefail

# ============================== CONFIG ==============================
OPENOBSERVE_INSECURE_TLS_VALUE="true"
OTEL_SERVICE_NAME_VALUE="github-copilot"
OTEL_CAPTURE_MESSAGE_CONTENT_VALUE="true"
OTEL_PROTOCOL_VALUE="http/protobuf"
OTEL_ENDPOINT_VALUE="https://34.14.177.44:4317"
COPILOT_OTEL_EXPORTER_TYPES_VALUE="otlp-http"
COPILOT_OTEL_ENABLED_VALUE="true"
COPILOT_OTEL_CAPTURE_CONTENT_VALUE="true"
# ======================================================================

# --- Prompt for the values that vary per user/machine ---
read -r -p 'OTEL resource attributes (e.g. team.name=team1,department.name=dept1,user=YourName,org=AMS): ' OTEL_RESOURCE_ATTRIBUTES_VALUE
if [ -z "$OTEL_RESOURCE_ATTRIBUTES_VALUE" ]; then
  echo 'OTEL resource attributes are required.' >&2
  exit 1
fi

read -r -p 'Path to OTEL exporter certificate (ca.crt): ' OTEL_CERTIFICATE_PATH_VALUE
if [ -z "$OTEL_CERTIFICATE_PATH_VALUE" ]; then
  echo 'OTEL certificate path is required.' >&2
  exit 1
fi
if [ ! -f "$OTEL_CERTIFICATE_PATH_VALUE" ]; then
  echo "Warning: certificate not found at '$OTEL_CERTIFICATE_PATH_VALUE' -- continuing anyway, but the OTEL exporter will fail until it exists." >&2
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
  echo "export OPENOBSERVE_INSECURE_TLS=\"$OPENOBSERVE_INSECURE_TLS_VALUE\""
  echo "export OTEL_RESOURCE_ATTRIBUTES=\"$OTEL_RESOURCE_ATTRIBUTES_VALUE\""
  echo "export OTEL_SERVICE_NAME=\"$OTEL_SERVICE_NAME_VALUE\""
  echo "export OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=\"$OTEL_CAPTURE_MESSAGE_CONTENT_VALUE\""
  echo "export OTEL_EXPORTER_OTLP_PROTOCOL=\"$OTEL_PROTOCOL_VALUE\""
  echo "export OTEL_EXPORTER_OTLP_ENDPOINT=\"$OTEL_ENDPOINT_VALUE\""
  echo "export OTEL_EXPORTER_OTLP_CERTIFICATE=\"$OTEL_CERTIFICATE_PATH_VALUE\""
  echo "export COPILOT_OTEL_EXPORTER_TYPES=\"$COPILOT_OTEL_EXPORTER_TYPES_VALUE\""
  echo "export COPILOT_OTEL_ENABLED=\"$COPILOT_OTEL_ENABLED_VALUE\""
  echo "export COPILOT_OTEL_CAPTURE_CONTENT=\"$COPILOT_OTEL_CAPTURE_CONTENT_VALUE\""
  echo "$MARKER_END"
} >> "$PROFILE_FILE"

# Also export into the current shell so it takes effect immediately, without a new terminal.
export OPENOBSERVE_INSECURE_TLS="$OPENOBSERVE_INSECURE_TLS_VALUE"
export OTEL_RESOURCE_ATTRIBUTES="$OTEL_RESOURCE_ATTRIBUTES_VALUE"
export OTEL_SERVICE_NAME="$OTEL_SERVICE_NAME_VALUE"
export OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT="$OTEL_CAPTURE_MESSAGE_CONTENT_VALUE"
export OTEL_EXPORTER_OTLP_PROTOCOL="$OTEL_PROTOCOL_VALUE"
export OTEL_EXPORTER_OTLP_ENDPOINT="$OTEL_ENDPOINT_VALUE"
export OTEL_EXPORTER_OTLP_CERTIFICATE="$OTEL_CERTIFICATE_PATH_VALUE"
export COPILOT_OTEL_EXPORTER_TYPES="$COPILOT_OTEL_EXPORTER_TYPES_VALUE"
export COPILOT_OTEL_ENABLED="$COPILOT_OTEL_ENABLED_VALUE"
export COPILOT_OTEL_CAPTURE_CONTENT="$COPILOT_OTEL_CAPTURE_CONTENT_VALUE"

echo "Wrote OTEL/Copilot env vars to $PROFILE_FILE and exported them into this shell."
echo "Open a new terminal (or run 'source $PROFILE_FILE') for other terminals/apps to see them."
echo
echo "Note: install-openobserve-agent.ps1's recurring scheduled task (Step 3) is Windows-only."
echo "On macOS, run the equivalent python commands by hand or wire them into cron/launchd, e.g.:"
echo "  */360 * * * * cd \"\$(dirname \"\$0\")/..\" && python3 generate_dashboard.py && python3 openobserve_export.py ..."
