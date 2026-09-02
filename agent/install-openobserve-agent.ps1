<#
.SYNOPSIS
  Installs (or removes) the "CopilotDashboardOpenObserve" scheduled task.

.EXAMPLE
  .\install-openobserve-agent.ps1 -IntervalMinutes 60

.EXAMPLE
  .\install-openobserve-agent.ps1 -Uninstall

.NOTES
  The password is stored DPAPI-encrypted under %LOCALAPPDATA%\copilot-dashboard
  and can only be read back by the same Windows user on the same machine, so the
  task definition never contains a secret. Because DPAPI needs the user's own
  session, the task is registered with an interactive logon type and therefore
  runs while the user is logged on.
#>
[CmdletBinding()]
param(
  [string]$TaskName = 'CopilotDashboardOpenObserve',
  [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
  [string]$ConfigPath = (Join-Path $PSScriptRoot 'config\agent-urls.json'),
  [string]$Url,
  [string]$UserName = 'admin@localhost.dev',
  [securestring]$Password,
  [string]$Python,
  [switch]$OpenObserveInsecureTls,
  [string]$PricingApiUrl,
  [double]$PricingCacheDays = (1.0 / 24.0),
  # The Copilot CLI store, which is where chronicle's tables live -- see the same parameter in
  # openobserve-agent.ps1 for why this is not the VS Code globalStorage path.
  [string]$ChronicleDb = (Join-Path $env:USERPROFILE '.copilot\session-store.db'),
  [string]$ChronicleBaseUrl,
  [string]$ChronicleOrg,
  [string]$ChronicleSince,
  [string]$ChronicleUser,
  [switch]$NoChronicle,
  [int]$IntervalMinutes = 60,
  [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'

# Fallback defaults if -ConfigPath is missing/unreadable or lacks a key.
$urlDefaults = @{
  OpenObserveUrl = 'https://localhost:5080/api/default/insights/_json'
  # Plain http on purpose -- see the same table in openobserve-agent.ps1.
  ChronicleBaseUrl = 'http://localhost:5080'
  ChronicleOrg   = 'default'
  PricingApiUrl  = 'https://localhost:8080/v1/copilot-pricing'
}
$urlConfig = $null
if (Test-Path -LiteralPath $ConfigPath) {
  try {
    $urlConfig = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
  } catch {
    Write-Warning "Failed to parse -ConfigPath '$ConfigPath': $_. Falling back to built-in defaults."
  }
}
function Get-UrlSetting {
  param([string]$Name)
  if ($urlConfig -and $urlConfig.PSObject.Properties.Name -contains $Name -and $urlConfig.$Name) {
    return $urlConfig.$Name
  }
  return $urlDefaults[$Name]
}
if (-not $Url) { $Url = Get-UrlSetting 'OpenObserveUrl' }
if (-not $ChronicleBaseUrl) { $ChronicleBaseUrl = Get-UrlSetting 'ChronicleBaseUrl' }
if (-not $ChronicleOrg) { $ChronicleOrg = Get-UrlSetting 'ChronicleOrg' }
if (-not $PricingApiUrl) { $PricingApiUrl = Get-UrlSetting 'PricingApiUrl' }

if ($Uninstall) {
  if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed scheduled task '$TaskName'."
  } else {
    Write-Host "Scheduled task '$TaskName' is not registered."
  }
  return
}

$runner = Join-Path $PSScriptRoot 'openobserve-agent.ps1'
if (-not (Test-Path -LiteralPath $runner)) { throw "Runner script not found: $runner" }

if (-not $Python) {
  $resolved = Get-Command python -ErrorAction SilentlyContinue
  if (-not $resolved) { throw 'python was not found on PATH. Re-run with -Python <full path to python.exe>.' }
  $Python = $resolved.Source
}

if (-not $Password) {
  $Password = Read-Host -AsSecureString "OpenObserve password for $UserName"
}

$credentialDir = Join-Path $env:LOCALAPPDATA 'copilot-dashboard'
if (-not (Test-Path -LiteralPath $credentialDir)) {
  New-Item -ItemType Directory -Path $credentialDir -Force | Out-Null
}
$credentialPath = Join-Path $credentialDir 'openobserve.cred.xml'
$credential = [pscustomobject]@{
  OpenObserveCredential = [pscredential]::new($UserName, $Password)
}
$credential | Export-Clixml -LiteralPath $credentialPath
Write-Host "Stored encrypted credentials at $credentialPath"

$arguments = @(
  '-NoProfile'
  '-NonInteractive'
  '-ExecutionPolicy'; 'Bypass'
  '-File'; "`"$runner`""
  '-RepoRoot'; "`"$RepoRoot`""
  '-ConfigPath'; "`"$ConfigPath`""
  '-Url'; "`"$Url`""
  '-Python'; "`"$Python`""
  '-CredentialPath'; "`"$credentialPath`""
  '-ChronicleDb'; "`"$ChronicleDb`""
  '-ChronicleBaseUrl'; "`"$ChronicleBaseUrl`""
  '-ChronicleOrg'; "`"$ChronicleOrg`""
  '-PricingApiUrl'; "`"$PricingApiUrl`""
  '-PricingCacheDays'; $PricingCacheDays.ToString([Globalization.CultureInfo]::InvariantCulture)
)
if ($ChronicleSince) { $arguments += @('-ChronicleSince'; "`"$ChronicleSince`"") }
if ($ChronicleUser) { $arguments += @('-ChronicleUser'; "`"$ChronicleUser`"") }
if ($NoChronicle) { $arguments += '-NoChronicle' }
if ($OpenObserveInsecureTls) { $arguments += '-OpenObserveInsecureTls' }
$arguments = $arguments -join ' '

$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments -WorkingDirectory $RepoRoot

$triggers = @(
  New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
  New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
)

# IgnoreNew is the scheduler-level guard against two runs posting the same batch.
$settings = New-ScheduledTaskSettingsSet `
  -MultipleInstances IgnoreNew `
  -StartWhenAvailable `
  -DontStopIfGoingOnBatteries `
  -AllowStartIfOnBatteries `
  -ExecutionTimeLimit (New-TimeSpan -Hours 1)

$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers `
  -Settings $settings -Principal $principal -Description 'Generates the Copilot usage dashboard, ships new insights to OpenObserve, and replays new Copilot CLI chronicle history into the copilot_chronicle_* streams.' -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName' (every $IntervalMinutes minute(s) and at logon)."
Write-Host "Insights stream:   $Url"
Write-Host "Chronicle streams: $ChronicleBaseUrl/api/$ChronicleOrg/copilot_chronicle_{usage,costs,sessions,files,turns}/_json"
Write-Host "Per-stream URL overrides: the 'ChronicleStreamUrls' object in $ConfigPath"
Write-Host "Run it now with: Start-ScheduledTask -TaskName $TaskName"
Write-Host "Log file: $(Join-Path $credentialDir 'agent.log')"
