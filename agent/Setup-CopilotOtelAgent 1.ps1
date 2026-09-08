<#
.SYNOPSIS
  Wrapper: sets the Copilot:8080 environment variables and registers the
  OpenObserve agent scheduled task in one step.

.DESCRIPTION
  Edit the values in the CONFIG block below to match your environment, then run:

    powershell -ExecutionPolicy Bypass -File .\Setup-CopilotOtelAgent.ps1

  This does not change your machine/user PowerShell execution policy -- the
  Bypass flag only applies to this one invocation.

.NOTES
  Re-run any time you change a value below; environment variables are
  overwritten and the scheduled task registration is idempotent (-Force).
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

# Scoped to this process only; does not touch the CurrentUser/LocalMachine policy.
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force

# ============================== CONFIG ==============================
$OpenObserveInsecureTls = $true
$OtelServiceName        = 'github-copilot'
$OtelCaptureContent     = $true
$OtelProtocol           = 'http/protobuf'
$OtelEndpoint           = 'https://34.14.177.44:8080'
$CopilotOtelExporter    = 'otlp-http'
$CopilotOtelEnabled     = $true
$CopilotOtelCaptureContent = $true

$InsightsUrl        = 'https://34.14.177.44/api/default/insights/_json'
$ChronicleBaseUrl   = 'https://34.14.177.44'
$ChronicleOrg       = 'default'
$PricingApiUrl      = 'https://34.14.177.44/v1/copilot-pricing'
$OpenObserveUserName = 'admin@localhost.dev'
$IntervalMinutes    = 360
# ======================================================================

# --- Prompt for the values that vary per user/machine ---
$OtelResourceAttributes = Read-Host 'OTEL resource attributes (e.g. team.name=team1,department.name=dept1,user=YourName,org=AMS)'
if (-not $OtelResourceAttributes) { throw 'OTEL resource attributes are required.' }

$OtelCertificatePath = Read-Host 'Path to OTEL exporter certificate (ca.crt)'
if (-not $OtelCertificatePath) { throw 'OTEL certificate path is required.' }
if (-not (Test-Path -LiteralPath $OtelCertificatePath)) {
  Write-Warning "Certificate not found at '$OtelCertificatePath' -- continuing anyway, but the OTEL exporter will fail until it exists."
}

# --- Step 1: persist the OTEL / Copilot environment variables for this user ---
$envVars = @{
  OPENOBSERVE_INSECURE_TLS                              = "$OpenObserveInsecureTls".ToLower()
  OTEL_RESOURCE_ATTRIBUTES                               = $OtelResourceAttributes
  OTEL_SERVICE_NAME                                      = $OtelServiceName
  OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT     = "$OtelCaptureContent".ToLower()
  OTEL_EXPORTER_OTLP_PROTOCOL                            = $OtelProtocol
  OTEL_EXPORTER_OTLP_ENDPOINT                            = $OtelEndpoint
  OTEL_EXPORTER_OTLP_CERTIFICATE                         = $OtelCertificatePath
  COPILOT_OTEL_EXPORTER_TYPES                            = $CopilotOtelExporter
  COPILOT_OTEL_ENABLED                                   = "$CopilotOtelEnabled".ToLower()
  COPILOT_OTEL_CAPTURE_CONTENT                           = "$CopilotOtelCaptureContent".ToLower()
}
foreach ($name in $envVars.Keys) {
  [Environment]::SetEnvironmentVariable($name, $envVars[$name], 'User')
  Set-Item -Path "Env:$name" -Value $envVars[$name]
}
Write-Host "Set $($envVars.Count) environment variable(s) at User scope (open a new terminal/VS Code window for other processes to see them)."

# --- Step 2: register the scheduled task, calling the installer in-process so ---
# --- $PSScriptRoot resolves inside its param-block defaults (see repo notes). ---
$installer = Join-Path $PSScriptRoot 'install-openobserve-agent.ps1'
if (-not (Test-Path -LiteralPath $installer)) { throw "Installer not found next to this wrapper: $installer" }

& $installer `
  -Url $InsightsUrl `
  -ChronicleBaseUrl $ChronicleBaseUrl `
  -ChronicleOrg $ChronicleOrg `
  -PricingApiUrl $PricingApiUrl `
  -UserName $OpenObserveUserName `
  -IntervalMinutes $IntervalMinutes `
  -OpenObserveInsecureTls:$OpenObserveInsecureTls
