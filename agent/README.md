# Copilot & Claude Code OpenTelemetry Agent Setup

Unified setup script for configuring GitHub Copilot and Claude Code telemetry with OpenObserve.

## Overview

`Setup-CopilotOtelAgent.ps1` configures three things in one step:
1. **Environment variables** for Copilot OTLP export (User scope)
2. **Claude Code telemetry** in `~/.claude/settings.json`
3. **Scheduled task** for insights/chronicle/pricing ingestion

## Prerequisites

### Windows
- **PowerShell 5.1+**
- **Python 3.x** on PATH (for the scheduled agent)
- **Docker Desktop** (for LOCAL mode) or access to remote OpenObserve server
- **OpenObserve instance** running (local or remote)

### macOS/Linux
- **Bash/Zsh**
- **Python 3.x** on PATH (optional, for manual dashboard generation)
- **Docker** (for LOCAL mode) or access to remote OpenObserve server
- **OpenObserve instance** running (local or remote)

## Quick Start

### Windows

#### Local Docker (Default)
```powershell
# Start your Docker observability stack first
cd C:\rdwr-intelij\observability
docker compose up -d

# Run setup (defaults to LOCAL mode)
cd C:\rdwr-intelij\rdwr-copilot_dashboard-openobserve-agent\agent
powershell -ExecutionPolicy Bypass -File .\Setup-CopilotOtelAgent.ps1
```

#### Remote Server
```powershell
powershell -ExecutionPolicy Bypass -File .\Setup-CopilotOtelAgent.ps1 -Mode REMOTE
```

### macOS/Linux

#### Local Docker (Default)
```bash
# Start your Docker observability stack first
cd /path/to/observability
docker compose up -d

# Run setup (defaults to local mode)
cd /path/to/rdwr-copilot_dashboard-openobserve-agent/agent
chmod +x setup-copilot-otel-env.sh
./setup-copilot-otel-env.sh
```

#### Remote Server
```bash
./setup-copilot-otel-env.sh remote
```

**Note**: The shell script only configures environment variables. Windows scheduled task features are not available on macOS/Linux. See [macOS/Linux Limitations](#macoslinux-limitations) below.

## Command-Line Parameters

### Mode Selection

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `-Mode` | String | `LOCAL` | Target environment: `LOCAL` (Docker localhost) or `REMOTE` (production server) |

### Chronicle Advice Capture

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `-ChronicleAdvice` | Switch | `false` | Enable Chronicle advice capture (⚠️ makes billed model calls) |
| `-ChronicleAdviceIntervalDays` | Double | `7` | How often to capture advice (in days) |
| `-ChronicleAdviceCommands` | String[] | (all) | Which commands to capture: `standup`, `tips`, `cost-tips`, `improve` |
| `-ChronicleAdviceNoSummary` | Switch | `false` | Skip the summary when capturing advice |

## Configuration by Mode

### LOCAL Mode (Default)
- **OpenObserve**: `http://localhost:5080`
- **Copilot OTLP**: `http://localhost:4318` (HTTP)
- **Claude Code OTLP**: `http://localhost:4418` (HTTP)
- **Organization**: `default`
- **Username**: `admin@localhost.dev`
- **Password**: `OpenObserve1!` (default)
- **TLS/Auth**: None required

### REMOTE Mode
- **OpenObserve**: `https://34.14.177.44`
- **Copilot OTLP**: `https://34.14.177.44:8080` (HTTPS)
- **Claude Code OTLP**: `https://34.14.177.44:8080` (HTTPS)
- **Organization**: `default`
- **Username**: `admin@localhost.dev`
- **TLS/Auth**: Required (prompts for certificate path)

## Usage Examples

### Basic Setup

#### Local Development (Default)
```powershell
# Minimal - uses all defaults
powershell -ExecutionPolicy Bypass -File .\Setup-CopilotOtelAgent.ps1
```

When prompted:
- **OTEL resource attributes**: `team.name=yourteam,department.name=engineering,user=YourName,org=AMS`
- **Password**: `OpenObserve1!` (default for local Docker)

#### Remote Server
```powershell
powershell -ExecutionPolicy Bypass -File .\Setup-CopilotOtelAgent.ps1 -Mode REMOTE
```

When prompted:
- **OTEL resource attributes**: `team.name=yourteam,department.name=engineering,user=YourName,org=AMS`
- **Certificate path**: `C:\path\to\ca.crt`
- **Password**: Your actual server password

### With Chronicle Advice

#### Enable Basic Advice (Every 7 Days, All Commands)
```powershell
powershell -ExecutionPolicy Bypass -File .\Setup-CopilotOtelAgent.ps1 `
  -ChronicleAdvice
```

#### Capture Only Daily Standup (Every 1 Day)
```powershell
powershell -ExecutionPolicy Bypass -File .\Setup-CopilotOtelAgent.ps1 `
  -ChronicleAdvice `
  -ChronicleAdviceIntervalDays 1 `
  -ChronicleAdviceCommands standup
```

#### Multiple Commands, Custom Interval
```powershell
powershell -ExecutionPolicy Bypass -File .\Setup-CopilotOtelAgent.ps1 `
  -ChronicleAdvice `
  -ChronicleAdviceIntervalDays 3 `
  -ChronicleAdviceCommands standup,tips,cost-tips
```

#### Skip Summary (Faster, Less Detail)
```powershell
powershell -ExecutionPolicy Bypass -File .\Setup-CopilotOtelAgent.ps1 `
  -ChronicleAdvice `
  -ChronicleAdviceNoSummary
```

### Complete Examples

#### Local + Full Advice
```powershell
powershell -ExecutionPolicy Bypass -File .\Setup-CopilotOtelAgent.ps1 `
  -Mode LOCAL `
  -ChronicleAdvice `
  -ChronicleAdviceIntervalDays 7 `
  -ChronicleAdviceCommands standup,tips,cost-tips,improve
```

#### Remote + Weekly Standup Only
```powershell
powershell -ExecutionPolicy Bypass -File .\Setup-CopilotOtelAgent.ps1 `
  -Mode REMOTE `
  -ChronicleAdvice `
  -ChronicleAdviceIntervalDays 7 `
  -ChronicleAdviceCommands standup `
  -ChronicleAdviceNoSummary
```

## What Gets Configured

### 1. Environment Variables (User Scope)
The following environment variables are set for your user:
- `OPENOBSERVE_INSECURE_TLS`
- `OTEL_RESOURCE_ATTRIBUTES`
- `OTEL_SERVICE_NAME`
- `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`
- `OTEL_EXPORTER_OTLP_PROTOCOL`
- `OTEL_EXPORTER_OTLP_ENDPOINT`
- `OTEL_EXPORTER_OTLP_CERTIFICATE` (REMOTE mode only)
- `COPILOT_OTEL_EXPORTER_TYPES`
- `COPILOT_OTEL_ENABLED`
- `COPILOT_OTEL_CAPTURE_CONTENT`

⚠️ **Important**: Open a new terminal/VS Code window after setup for these to take effect.

### 2. Claude Code Configuration (`~/.claude/settings.json`)
The following settings are merged into your Claude Code config:
```json
{
  "env": {
    "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
    "OTEL_METRICS_EXPORTER": "otlp",
    "OTEL_LOGS_EXPORTER": "otlp",
    "OTEL_TRACES_EXPORTER": "otlp",
    "CLAUDE_CODE_ENHANCED_TELEMETRY_BETA": "1",
    "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4418",
    "OTEL_SERVICE_NAME": "claude-code",
    "OTEL_RESOURCE_ATTRIBUTES": "...",
    "OTEL_LOG_USER_PROMPTS": "1",
    "OTEL_LOG_ASSISTANT_RESPONSES": "1"
  }
}
```

⚠️ **Important**: Restart Claude Code or start a new session for changes to take effect.

### 3. Scheduled Task
A Windows scheduled task named `CopilotDashboardOpenObserve` is registered:
- **Trigger**: At logon + every 6 hours (360 minutes, configurable)
- **Action**: Runs `openobserve-agent.ps1` to:
  - Generate Copilot usage dashboard
  - Ship insights to OpenObserve
  - Replay Copilot CLI chronicle history
  - Ship Claude Code usage
  - Capture Chronicle advice (if enabled)

View/manage: `Task Scheduler` → `Task Scheduler Library` → `CopilotDashboardOpenObserve`

## Environment Variable Overrides

You can override any endpoint without editing the script by setting these environment variables:

```powershell
# Override before running setup
$env:OPENOBSERVE_BASE_URL = 'http://custom-host:5080'
$env:COPILOT_OTEL_ENDPOINT = 'http://custom-host:4318'
$env:CLAUDE_OTEL_ENDPOINT = 'http://custom-host:4418'
$env:OPENOBSERVE_ORG = 'myorg'
$env:OPENOBSERVE_USER = 'myuser@example.com'

# Then run setup
powershell -ExecutionPolicy Bypass -File .\Setup-CopilotOtelAgent.ps1
```

## OpenObserve Streams

After setup, your telemetry is ingested into these streams:

### Copilot Streams
- `lld-agent` - Live OTLP traces/logs/metrics from Copilot
- `copilot_chronicle_usage` - CLI usage events
- `copilot_chronicle_costs` - Cost data
- `copilot_chronicle_sessions` - Session records
- `copilot_chronicle_files` - File-level statistics
- `copilot_chronicle_turns` - Turn-by-turn interactions
- `copilot_chronicle_advice` - Advice captures (if `-ChronicleAdvice` enabled)

### Claude Code Streams
- `claude-code` - Live OTLP traces/logs/metrics from Claude Code
- `claude_insights_sessions` - Session usage data

## Access OpenObserve Dashboard

### Local Mode
```
URL: http://localhost:5080
Username: admin@localhost.dev
Password: OpenObserve1!
```

### Remote Mode
```
URL: https://34.14.177.44
Username: admin@localhost.dev
Password: <your-server-password>
```

## Switching Between Local and Remote

You can switch modes at any time by re-running the setup with a different `-Mode`:

```powershell
# Switch to LOCAL
powershell -ExecutionPolicy Bypass -File .\Setup-CopilotOtelAgent.ps1 -Mode LOCAL

# Switch to REMOTE
powershell -ExecutionPolicy Bypass -File .\Setup-CopilotOtelAgent.ps1 -Mode REMOTE
```

This will:
- ✅ Update environment variables
- ✅ Update `~/.claude/settings.json`
- ✅ Update the scheduled task
- ⚠️ Require new terminal/VS Code window for env vars
- ⚠️ Require Claude Code restart for settings

## Troubleshooting

### Scheduled Task Not Running

1. **Check if task exists:**
   ```powershell
   Get-ScheduledTask -TaskName CopilotDashboardOpenObserve
   ```

2. **Check task history:**
   - Open Task Scheduler
   - Navigate to `CopilotDashboardOpenObserve`
   - View history tab

3. **Run manually:**
   ```powershell
   Start-ScheduledTask -TaskName CopilotDashboardOpenObserve
   ```

### Telemetry Not Appearing

1. **Verify Docker is running (LOCAL mode):**
   ```powershell
   docker ps
   # Should show: openobserve, observability-otel-collector-1
   ```

2. **Check environment variables:**
   ```powershell
   # In a NEW terminal window
   Get-ChildItem Env: | Where-Object { $_.Name -like '*OTEL*' -or $_.Name -like '*COPILOT*' }
   ```

3. **Check Claude Code settings:**
   ```powershell
   Get-Content "$env:USERPROFILE\.claude\settings.json"
   ```

4. **Test OTLP endpoint:**
   ```powershell
   # Local
   curl http://localhost:4318/v1/traces

   # Should return 405 Method Not Allowed (endpoint is alive)
   ```

### Connection Refused (LOCAL mode)

Make sure Docker containers are running:
```powershell
cd C:\rdwr-intelij\observability
docker compose up -d
docker compose ps
```

### Certificate Issues (REMOTE mode)

If you get TLS/certificate errors:
1. Ensure you provided the correct path to `ca.crt`
2. Check the certificate is valid and not expired
3. Try with `-OpenObserveInsecureTls` flag (not recommended for production)

## Uninstalling

To remove the scheduled task:
```powershell
.\install-openobserve-agent.ps1 -Uninstall
```

To remove environment variables:
```powershell
# Remove Copilot env vars
$vars = @(
  'OPENOBSERVE_INSECURE_TLS',
  'OTEL_RESOURCE_ATTRIBUTES',
  'OTEL_SERVICE_NAME',
  'OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT',
  'OTEL_EXPORTER_OTLP_PROTOCOL',
  'OTEL_EXPORTER_OTLP_ENDPOINT',
  'OTEL_EXPORTER_OTLP_CERTIFICATE',
  'COPILOT_OTEL_EXPORTER_TYPES',
  'COPILOT_OTEL_ENABLED',
  'COPILOT_OTEL_CAPTURE_CONTENT'
)
foreach ($var in $vars) {
  [Environment]::SetEnvironmentVariable($var, $null, 'User')
}
```

To remove Claude Code telemetry config, manually edit `~/.claude/settings.json` and remove the OTEL-related keys from the `env` object.

## Chronicle Advice Costs

⚠️ **Important**: Chronicle advice capture makes **billed model calls** to generate the advice content.

**Approximate costs per capture:**
- `standup`: ~1-2 model calls
- `tips`: ~2-3 model calls
- `cost-tips`: ~1-2 model calls
- `improve`: ~2-4 model calls

**Recommendations:**
- Start with longer intervals (7+ days) to monitor cost
- Use specific commands rather than all four
- Consider `-ChronicleAdviceNoSummary` to reduce calls

## macOS/Linux Limitations

The shell script (`setup-copilot-otel-env.sh`) only handles **environment variable configuration**. It does not:
- Configure Claude Code telemetry (manually edit `~/.claude/settings.json`)
- Install a scheduled task/cron job (set up manually if needed)
- Run the Python dashboard/chronicle scripts automatically

### Manual Claude Code Configuration (macOS/Linux)

Edit `~/.claude/settings.json` and merge these settings with your existing config:

#### For LOCAL Mode
Add these keys under the `env` object:
```json
"CLAUDE_CODE_ENABLE_TELEMETRY": "1",
"OTEL_METRICS_EXPORTER": "otlp",
"OTEL_LOGS_EXPORTER": "otlp",
"OTEL_TRACES_EXPORTER": "otlp",
"CLAUDE_CODE_ENHANCED_TELEMETRY_BETA": "1",
"OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
"OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4418",
"OTEL_SERVICE_NAME": "claude-code",
"OTEL_RESOURCE_ATTRIBUTES": "team.name=yourteam,department.name=engineering,user=YourName",
"OTEL_LOG_USER_PROMPTS": "1",
"OTEL_LOG_ASSISTANT_RESPONSES": "1"
```

Complete example:
```json
{
  "env": {
    "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
    "OTEL_METRICS_EXPORTER": "otlp",
    "OTEL_LOGS_EXPORTER": "otlp",
    "OTEL_TRACES_EXPORTER": "otlp",
    "CLAUDE_CODE_ENHANCED_TELEMETRY_BETA": "1",
    "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4418",
    "OTEL_SERVICE_NAME": "claude-code",
    "OTEL_RESOURCE_ATTRIBUTES": "team.name=yourteam,department.name=engineering,user=YourName",
    "OTEL_LOG_USER_PROMPTS": "1",
    "OTEL_LOG_ASSISTANT_RESPONSES": "1"
  }
}
```

#### For REMOTE Mode
Add these keys under the `env` object:
```json
"CLAUDE_CODE_ENABLE_TELEMETRY": "1",
"OTEL_METRICS_EXPORTER": "otlp",
"OTEL_LOGS_EXPORTER": "otlp",
"OTEL_TRACES_EXPORTER": "otlp",
"CLAUDE_CODE_ENHANCED_TELEMETRY_BETA": "1",
"OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
"OTEL_EXPORTER_OTLP_ENDPOINT": "https://34.14.177.44:8080",
"OTEL_SERVICE_NAME": "claude-code",
"OTEL_RESOURCE_ATTRIBUTES": "team.name=yourteam,department.name=engineering,user=YourName",
"OTEL_EXPORTER_OTLP_HEADERS": "Authorization=Basic <base64-encoded-credentials>,stream-name=claude-code",
"OTEL_EXPORTER_OTLP_CERTIFICATE": "/path/to/ca.crt",
"NODE_EXTRA_CA_CERTS": "/path/to/ca.crt",
"OTEL_LOG_USER_PROMPTS": "1",
"OTEL_LOG_ASSISTANT_RESPONSES": "1"
```

Complete example:
```json
{
  "env": {
    "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
    "OTEL_METRICS_EXPORTER": "otlp",
    "OTEL_LOGS_EXPORTER": "otlp",
    "OTEL_TRACES_EXPORTER": "otlp",
    "CLAUDE_CODE_ENHANCED_TELEMETRY_BETA": "1",
    "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "https://34.14.177.44:8080",
    "OTEL_SERVICE_NAME": "claude-code",
    "OTEL_RESOURCE_ATTRIBUTES": "team.name=yourteam,department.name=engineering,user=YourName",
    "OTEL_EXPORTER_OTLP_HEADERS": "Authorization=Basic <base64-encoded-credentials>,stream-name=claude-code",
    "OTEL_EXPORTER_OTLP_CERTIFICATE": "/path/to/ca.crt",
    "NODE_EXTRA_CA_CERTS": "/path/to/ca.crt",
    "OTEL_LOG_USER_PROMPTS": "1",
    "OTEL_LOG_ASSISTANT_RESPONSES": "1"
  }
}
```

Replace `<base64-encoded-credentials>` with the output of:
```bash
echo -n "admin@localhost.dev:your-password" | base64
```

### Optional: Set Up Cron Job (macOS/Linux)

To periodically run dashboard generation and data export:

```bash
# Edit crontab
crontab -e

# Add this line (runs every 6 hours)
0 */6 * * * cd /path/to/rdwr-copilot_dashboard-openobserve-agent && python3 generate_dashboard.py && python3 openobserve_export.py
```

Or use `launchd` on macOS for more control.

## Additional Resources

- **OpenObserve Docs**: https://openobserve.ai/docs
- **Claude Code Tracing**: https://openobserve.ai/docs/integration/ai/claude-code-tracing/
- **OpenTelemetry Spec**: https://opentelemetry.io/docs/specs/otel/

## Support

For issues or questions:
1. Check the troubleshooting section above
2. **Windows**: Review scheduled task logs in Task Scheduler
3. **macOS/Linux**: Check shell profile (`~/.zshrc` or `~/.bash_profile`) for env vars
4. Check OpenObserve logs: `docker compose logs openobserve -f` (LOCAL mode)
5. Check collector logs: `docker compose logs otel-collector -f` (LOCAL mode)
