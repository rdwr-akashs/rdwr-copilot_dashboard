<#
.SYNOPSIS
  Wrapper: sets the Copilot:8080 environment variables, registers the
  OpenObserve agent scheduled task, and wires Claude Code's own OTEL export
  into the same OpenObserve instance -- all in one step.

.DESCRIPTION
  Run with -Mode to choose LOCAL (Docker localhost) or REMOTE (production server):

    # Local Docker (default)
    powershell -ExecutionPolicy Bypass -File .\Setup-CopilotOtelAgent.ps1

    # Remote server
    powershell -ExecutionPolicy Bypass -File .\Setup-CopilotOtelAgent.ps1 -Mode REMOTE

  This does not change your machine/user PowerShell execution policy -- the
  Bypass flag only applies to this one invocation.

  Claude Code telemetry is configured per OpenObserve's documented setup
  (env vars live in ~/.claude/settings.json, not shell env vars):
  https://openobserve.ai/docs/integration/ai/claude-code-tracing/

  To enable Chronicle advice capture (opt-in, billed model calls):
    powershell -ExecutionPolicy Bypass -File .\Setup-CopilotOtelAgent.ps1 -ChronicleAdvice

  To customize advice capture with remote server:
    powershell -ExecutionPolicy Bypass -File .\Setup-CopilotOtelAgent.ps1 `
      -Mode REMOTE `
      -ChronicleAdvice `
      -ChronicleAdviceIntervalDays 3 `
      -ChronicleAdviceCommands standup

.NOTES
  Re-run any time you change a value below; environment variables are
  overwritten, ~/.claude/settings.json is merged in place, and the scheduled
  task registration is idempotent (-Force).
#>
[CmdletBinding()]
param(
  # Mode: 'LOCAL' for Docker localhost, 'REMOTE' for production server
  [ValidateSet('LOCAL', 'REMOTE')]
  [string]$Mode = 'LOCAL',

  # Enable Chronicle advice capture (standup, tips, cost-tips, improve)
  # Note: This makes billed model calls, so it's opt-in
  [switch]$ChronicleAdvice,

  # How often to capture advice (default: 7 days)
  [double]$ChronicleAdviceIntervalDays = 7,

  # Which commands to capture (e.g., 'standup', 'tips', 'cost-tips', 'improve')
  # If not specified, all advice commands are captured
  [string[]]$ChronicleAdviceCommands,

  # Skip the summary when capturing advice
  [switch]$ChronicleAdviceNoSummary
)

$ErrorActionPreference = 'Stop'

# Scoped to this process only; does not touch the CurrentUser/LocalMachine policy.
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force

# Reads $env:<Name> if set, otherwise falls back to $Default -- lets every
# endpoint below be repointed (e.g. at a local Docker OpenObserve) without
# editing this file. Same convention this repo's Python exporters already
# use for $OPENOBSERVE_BASE_URL / $OPENOBSERVE_ORG (see README "Chronicle").
function Get-ConfigValue {
  param([string]$EnvName, [string]$Default)
  $value = [Environment]::GetEnvironmentVariable($EnvName)
  if ($value) { return $value }
  return $Default
}

# ============================== CONFIG ==============================
# Mode is set via -Mode parameter (default: LOCAL)
#   LOCAL  - Docker stack at localhost (C:\rdwr-intelij\observability)
#   REMOTE - Production server at 34.14.177.44
# ====================================================================

if ($Mode -eq 'LOCAL') {
  # Local Docker configuration (no TLS, no auth headers needed)
  $OpenObserveBaseUrl  = 'http://localhost:5080'
  $CopilotOtelEndpoint = 'http://localhost:4318'
  $ClaudeOtelEndpoint  = 'http://localhost:4418'
  $OpenObserveOrg      = 'default'
  $OpenObserveUserName = 'admin@localhost.dev'
  Write-Host "*** MODE: LOCAL (Docker localhost) ***" -ForegroundColor Cyan
} elseif ($Mode -eq 'REMOTE') {
  # Remote server configuration (TLS + auth required)
  $OpenObserveBaseUrl  = 'https://34.14.177.44'
  $CopilotOtelEndpoint = 'https://34.14.177.44:8080'
  $ClaudeOtelEndpoint  = 'https://34.14.177.44:8080'
  $OpenObserveOrg      = 'default'
  $OpenObserveUserName = 'admin@localhost.dev'
  Write-Host "*** MODE: REMOTE (34.14.177.44) ***" -ForegroundColor Yellow
} else {
  throw "Invalid mode '$Mode'. Set `$Mode to 'LOCAL' or 'REMOTE' in the CONFIG section."
}

# Environment variables can still override these values if needed
$OpenObserveBaseUrl  = (Get-ConfigValue 'OPENOBSERVE_BASE_URL'  $OpenObserveBaseUrl).TrimEnd('/')
$CopilotOtelEndpoint = (Get-ConfigValue 'COPILOT_OTEL_ENDPOINT' $CopilotOtelEndpoint).TrimEnd('/')
$ClaudeOtelEndpoint  = (Get-ConfigValue 'CLAUDE_OTEL_ENDPOINT'  $ClaudeOtelEndpoint).TrimEnd('/')

# TLS/auth/cert-verification settings only apply to the direct-to-OpenObserve
# remote path; a local collector target (http://) neither needs nor accepts any of them.
$CopilotNeedsTls = $CopilotOtelEndpoint.StartsWith('https://')
$ClaudeNeedsAuth = $ClaudeOtelEndpoint.StartsWith('https://')
$NeedsCert       = $CopilotNeedsTls -or $ClaudeNeedsAuth

$OpenObserveInsecureTls = $NeedsCert
$OtelServiceName        = 'github-copilot'
$OtelCaptureContent     = $true
$OtelProtocol           = Get-ConfigValue 'OTEL_EXPORTER_OTLP_PROTOCOL' 'http/protobuf'
$CopilotOtelExporter    = 'otlp-http'
$CopilotOtelEnabled     = $true
$CopilotOtelCaptureContent = $true

$InsightsUrl        = "$OpenObserveBaseUrl/api/$OpenObserveOrg/insights/_json"
$ChronicleBaseUrl   = $OpenObserveBaseUrl
$ChronicleOrg       = $OpenObserveOrg
$PricingApiUrl      = "$CopilotOtelEndpoint/v1/copilot-pricing"
$IntervalMinutes    = 360
# ======================================================================

# --- Prompt for the values that vary per user/machine ---
Write-Host "`nNote: Resource attributes are set via environment variables in docker-compose.yaml for LOCAL mode." -ForegroundColor Gray
Write-Host "      This prompt is for the agent/collector attribution." -ForegroundColor Gray
$OtelResourceAttributes = Read-Host 'OTEL resource attributes (e.g. team.name=team1,department.name=dept1,user=YourName,org=AMS)'
if (-not $OtelResourceAttributes) { throw 'OTEL resource attributes are required.' }

$OtelCertificatePath = $null
if ($NeedsCert) {
  $OtelCertificatePath = Read-Host 'Path to OTEL exporter certificate (ca.crt)'
  if (-not $OtelCertificatePath) { throw 'OTEL certificate path is required when an endpoint above uses https://.' }
  if (-not (Test-Path -LiteralPath $OtelCertificatePath)) {
    Write-Warning "Certificate not found at '$OtelCertificatePath' -- continuing anyway, but the OTEL exporter will fail until it exists."
  }
} else {
  Write-Host 'Skipping the OTEL certificate prompt: both OTLP endpoints are http:// (no TLS, no cert needed).'
}

# --- Step 1: persist the OTEL / Copilot environment variables for this user ---
$envVars = [ordered]@{
  OTEL_RESOURCE_ATTRIBUTES                               = $OtelResourceAttributes
  OTEL_SERVICE_NAME                                      = $OtelServiceName
  OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT     = "$OtelCaptureContent".ToLower()
  OTEL_EXPORTER_OTLP_PROTOCOL                            = $OtelProtocol
  OTEL_EXPORTER_OTLP_ENDPOINT                            = $CopilotOtelEndpoint
  COPILOT_OTEL_EXPORTER_TYPES                            = $CopilotOtelExporter
  COPILOT_OTEL_ENABLED                                   = "$CopilotOtelEnabled".ToLower()
  COPILOT_OTEL_CAPTURE_CONTENT                           = "$CopilotOtelCaptureContent".ToLower()
}
if ($CopilotNeedsTls) {
  $envVars['OPENOBSERVE_INSECURE_TLS'] = "$OpenObserveInsecureTls".ToLower()
  $envVars['OTEL_EXPORTER_OTLP_CERTIFICATE'] = $OtelCertificatePath
}
foreach ($name in $envVars.Keys) {
  [Environment]::SetEnvironmentVariable($name, $envVars[$name], 'User')
  Set-Item -Path "Env:$name" -Value $envVars[$name]
}
# Clear stale TLS settings left over from a previous REMOTE run -- otherwise
# switching back to LOCAL keeps pointing OTEL at a certificate it no longer needs.
if (-not $CopilotNeedsTls) {
  foreach ($staleName in @('OPENOBSERVE_INSECURE_TLS', 'OTEL_EXPORTER_OTLP_CERTIFICATE')) {
    [Environment]::SetEnvironmentVariable($staleName, $null, 'User')
    if (Test-Path "Env:$staleName") { Remove-Item "Env:$staleName" }
  }
}
Write-Host "Set $($envVars.Count) environment variable(s) at User scope (open a new terminal/VS Code window for other processes to see them)."

# --- Step 2: wire Claude Code's own OTEL export into the same OpenObserve instance ---
# Reference: https://openobserve.ai/docs/integration/ai/claude-code-tracing/
$ClaudeSettingsPath  = Join-Path $env:USERPROFILE '.claude\settings.json'
$ClaudeOtelStreamName = 'claude-code'

# This password is also needed for Step 3 (Chronicle/insights/pricing hit
# OpenObserve's own basic-auth API regardless of the OTLP path chosen above),
# so it's always prompted for -- only the *header* built from it is optional.
# For LOCAL mode default: OpenObserve1!
# For REMOTE mode: use your actual server password
$OpenObservePassword = Read-Host "OpenObserve password for '$OpenObserveUserName' [LOCAL default: OpenObserve1!]" -AsSecureString

$claudeEnv = [ordered]@{
  CLAUDE_CODE_ENABLE_TELEMETRY        = '1'
  OTEL_METRICS_EXPORTER               = 'otlp'
  OTEL_LOGS_EXPORTER                  = 'otlp'
  OTEL_TRACES_EXPORTER                = 'otlp'
  CLAUDE_CODE_ENHANCED_TELEMETRY_BETA = '1'
  OTEL_EXPORTER_OTLP_PROTOCOL         = $OtelProtocol
  OTEL_EXPORTER_OTLP_ENDPOINT         = $ClaudeOtelEndpoint
  OTEL_SERVICE_NAME                   = 'claude-code'
  OTEL_RESOURCE_ATTRIBUTES            = $OtelResourceAttributes
  OTEL_LOG_USER_PROMPTS               = '1'
  OTEL_LOG_ASSISTANT_RESPONSES        = '1'
}
if ($ClaudeNeedsAuth) {
  $OpenObservePasswordPlain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToGlobalAllocUnicode($OpenObservePassword)
  )
  $claudeAuthToken = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("${OpenObserveUserName}:${OpenObservePasswordPlain}"))
  $OpenObservePasswordPlain = $null
  $claudeEnv['OTEL_EXPORTER_OTLP_HEADERS'] = "Authorization=Basic $claudeAuthToken,stream-name=$ClaudeOtelStreamName"
  $claudeEnv['OTEL_EXPORTER_OTLP_CERTIFICATE'] = $OtelCertificatePath
  $claudeEnv['NODE_EXTRA_CA_CERTS'] = $OtelCertificatePath
}

$claudeSettingsDir = Split-Path -Parent $ClaudeSettingsPath
if (-not (Test-Path -LiteralPath $claudeSettingsDir)) {
  New-Item -ItemType Directory -Path $claudeSettingsDir -Force | Out-Null
}

$claudeSettings = if (Test-Path -LiteralPath $ClaudeSettingsPath) {
  Get-Content -LiteralPath $ClaudeSettingsPath -Raw | ConvertFrom-Json
} else {
  [PSCustomObject]@{}
}

if (-not $claudeSettings.PSObject.Properties['env']) {
  $claudeSettings | Add-Member -NotePropertyName 'env' -NotePropertyValue ([PSCustomObject]@{})
}
foreach ($key in $claudeEnv.Keys) {
  if ($claudeSettings.env.PSObject.Properties[$key]) {
    $claudeSettings.env.$key = $claudeEnv[$key]
  } else {
    $claudeSettings.env | Add-Member -NotePropertyName $key -NotePropertyValue $claudeEnv[$key]
  }
}
# Clear stale TLS/auth settings left over from a previous REMOTE run -- otherwise
# switching back to LOCAL keeps pointing Claude Code at a certificate/header it no longer needs.
if (-not $ClaudeNeedsAuth) {
  foreach ($staleKey in @('OTEL_EXPORTER_OTLP_HEADERS', 'OTEL_EXPORTER_OTLP_CERTIFICATE', 'NODE_EXTRA_CA_CERTS')) {
    if ($claudeSettings.env.PSObject.Properties[$staleKey]) {
      $claudeSettings.env.PSObject.Properties.Remove($staleKey)
    }
  }
}

$claudeSettings | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $ClaudeSettingsPath -Encoding UTF8
Write-Host "Merged Claude Code OTEL config into $ClaudeSettingsPath (other settings in that file are preserved; restart Claude Code / open a new session for it to take effect)."

# --- Step 3: register the scheduled task, calling the installer in-process so ---
# --- $PSScriptRoot resolves inside its param-block defaults (see repo notes). ---
$installer = Join-Path $PSScriptRoot 'install-openobserve-agent.ps1'
if (-not (Test-Path -LiteralPath $installer)) { throw "Installer not found next to this wrapper: $installer" }

$installerArgs = @{
  Url = $InsightsUrl
  ChronicleBaseUrl = $ChronicleBaseUrl
  ChronicleOrg = $ChronicleOrg
  PricingApiUrl = $PricingApiUrl
  UserName = $OpenObserveUserName
  Password = $OpenObservePassword
  IntervalMinutes = $IntervalMinutes
  OpenObserveInsecureTls = $OpenObserveInsecureTls
}

# Pass through Chronicle advice parameters if enabled
if ($ChronicleAdvice) {
  $installerArgs['ChronicleAdvice'] = $true
  $installerArgs['ChronicleAdviceIntervalDays'] = $ChronicleAdviceIntervalDays
  if ($ChronicleAdviceCommands) {
    $installerArgs['ChronicleAdviceCommands'] = $ChronicleAdviceCommands
  }
  if ($ChronicleAdviceNoSummary) {
    $installerArgs['ChronicleAdviceNoSummary'] = $true
  }
}

& $installer @installerArgs
