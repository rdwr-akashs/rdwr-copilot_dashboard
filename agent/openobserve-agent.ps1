<#
.SYNOPSIS
  Runs the Copilot dashboard generator and ships insights to OpenObserve.

.DESCRIPTION
  Intended to be launched by the "CopilotDashboardOpenObserve" scheduled task
  created by install-openobserve-agent.ps1, but it can also be run by hand.

  Duplicate protection has two layers:
    1. A lock file, so two overlapping runs never post the same batch twice.
    2. generate_dashboard.py's own de-duplication state file, which fingerprints
       every event already accepted by the endpoint and skips it next time.

  The same run also replays the Copilot CLI's chronicle history into the
  copilot_chronicle_* streams (chronicle_export.py), unless -NoChronicle is
  passed. That half has its own duplicate protection and does not use the
  fingerprint file above: chronicle rows are immutable and counted in thousands,
  so they are tracked by a high-water mark per source table (-ChronicleStatePath)
  which only advances on a batch OpenObserve accepted in full.
#>
[CmdletBinding()]
param(
  [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
  [string]$ConfigPath = (Join-Path $PSScriptRoot 'config\agent-urls.json'),
  [string]$Url,
  [string]$Python = 'python',
  [switch]$OpenObserveInsecureTls,
  [string]$CredentialPath = (Join-Path $env:LOCALAPPDATA 'copilot-dashboard\openobserve.cred.xml'),
  [string]$StatePath = (Join-Path $env:USERPROFILE '.copilot-dashboard\openobserve_sent.json'),
  # The Copilot *CLI* store, not the VS Code chat extension's globalStorage file this
  # parameter used to default to. Chronicle's tables -- assistant_usage_events, sessions,
  # session_files, turns -- belong to the CLI, so the old default named a file the export
  # cannot read anything out of. Nothing broke, because nothing used the parameter.
  [string]$ChronicleDb = (Join-Path $env:USERPROFILE '.copilot\session-store.db'),
  [switch]$NoChronicle,
  [string]$ChronicleBaseUrl,
  # The '/api/<org>/' segment of every chronicle stream URL.
  [string]$ChronicleOrg,
  # Full per-stream overrides, e.g. -ChronicleStreamUrls @{ copilot_chronicle_turns =
  # 'https://oo.example.com/api/team/turns/_json' }. A stream left out keeps the base + org
  # form. Also settable as a "ChronicleStreamUrls" object in agent-urls.json, which is how the
  # scheduled task gets it -- the task action carries -ConfigPath, not a hashtable literal.
  [hashtable]$ChronicleStreamUrls,
  # Deprecated: a single full stream URL. Chronicle writes five streams, so it takes a base
  # and appends each one itself. Kept as an alias so an already-registered scheduled task,
  # whose action still passes -ChronicleUrl, keeps starting instead of failing on an unknown
  # parameter. The base is derived from it below.
  [string]$ChronicleUrl,
  # A floor on how far back to replay. Worth setting: chronicle's sessions and turns reach
  # further back than its billed calls do, so without it the per-session ratios divide by
  # sessions that could not have spent a credit.
  [string]$ChronicleSince,
  [string]$ChronicleUser,
  [string]$ChronicleStatePath = (Join-Path $env:USERPROFILE '.copilot-dashboard\chronicle_state.json'),
  [string]$PricingApiUrl,
  [double]$PricingCacheDays = (1.0 / 24.0),
  [string]$LogPath = (Join-Path $env:LOCALAPPDATA 'copilot-dashboard\agent.log')
)

$ErrorActionPreference = 'Stop'

# Fallback defaults if -ConfigPath is missing/unreadable or lacks a key.
$urlDefaults = @{
  OpenObserveUrl = 'https://localhost:5080/api/default/insights/_json'
  # Plain http, unlike the insights default above: this is what a stock OpenObserve container
  # actually listens for. An https URL against it fails the handshake rather than returning an
  # error a log line could explain. Override in agent-urls.json for a host with TLS.
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
if (-not $PricingApiUrl) { $PricingApiUrl = Get-UrlSetting 'PricingApiUrl' }
if (-not $ChronicleBaseUrl) {
  if ($ChronicleUrl) {
    # Strip the /api/<org>/<stream>/_json tail off a legacy value so an old task definition
    # still points at the right server rather than at a URL with a stream name baked in.
    $ChronicleBaseUrl = ($ChronicleUrl -replace '/api/.*$', '')
  } else {
    $ChronicleBaseUrl = Get-UrlSetting 'ChronicleBaseUrl'
  }
}
if (-not $ChronicleOrg) { $ChronicleOrg = Get-UrlSetting 'ChronicleOrg' }
if (-not $ChronicleStreamUrls -and $urlConfig -and
    $urlConfig.PSObject.Properties.Name -contains 'ChronicleStreamUrls' -and
    $urlConfig.ChronicleStreamUrls) {
  $ChronicleStreamUrls = @{}
  foreach ($entry in $urlConfig.ChronicleStreamUrls.PSObject.Properties) {
    if ($entry.Value) { $ChronicleStreamUrls[$entry.Name] = [string]$entry.Value }
  }
}

function Write-Log {
  param([string]$Message, [string]$Level = 'INFO')
  $line = '{0} [{1}] {2}' -f (Get-Date -Format 'yyyy-MM-ddTHH:mm:ssK'), $Level, $Message
  $dir = Split-Path -Parent $LogPath
  if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
  Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8
  Write-Output $line
}

if (-not (Test-Path -LiteralPath $CredentialPath)) {
  Write-Log "Credential file not found: $CredentialPath. Run install-openobserve-agent.ps1 first." 'ERROR'
  exit 2
}

# DPAPI-protected, decryptable only by the installing user on this machine.
$credential = Import-Clixml -LiteralPath $CredentialPath
$openObserveCredential = if ($credential -is [pscredential]) {
  $credential
} else {
  $credential.OpenObserveCredential
}

$lockPath = Join-Path ([System.IO.Path]::GetDirectoryName($LogPath)) 'agent.lock'
$lock = $null
try {
  $lock = [System.IO.File]::Open($lockPath, 'OpenOrCreate', 'ReadWrite', 'None')
} catch {
  Write-Log 'Another agent run is already in progress; exiting without sending.' 'WARN'
  exit 0
}

try {
  $env:OPENOBSERVE_USER = $openObserveCredential.UserName
  $env:OPENOBSERVE_PASSWORD = $openObserveCredential.GetNetworkCredential().Password
  $env:COPILOT_PRICING_API_URL = $PricingApiUrl
  $env:COPILOT_PRICING_CACHE_DAYS = $PricingCacheDays.ToString([Globalization.CultureInfo]::InvariantCulture)

  Push-Location $RepoRoot
  try {
    Write-Log "Running generator against $Url"
    # Windows PowerShell turns redirected native stderr into terminating errors
    # under 'Stop'; the generator logs its progress there, so relax it here.
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $generatorArguments = @('--openobserve', '--openobserve-url', $Url, '--openobserve-state', $StatePath)
    if ($OpenObserveInsecureTls) { $generatorArguments += '--openobserve-insecure-tls' }
    if (-not $NoChronicle) {
      if (Test-Path -LiteralPath $ChronicleDb) {
        Write-Log "Chronicle: replaying $ChronicleDb into $ChronicleBaseUrl/api/$ChronicleOrg/<stream>/_json"
        $generatorArguments += @(
          '--chronicle'
          '--chronicle-db'; $ChronicleDb
          '--chronicle-base-url'; $ChronicleBaseUrl
          '--chronicle-org'; $ChronicleOrg
          '--chronicle-state'; $ChronicleStatePath
        )
        if ($ChronicleStreamUrls) {
          foreach ($stream in $ChronicleStreamUrls.Keys) {
            $streamUrl = $ChronicleStreamUrls[$stream]
            if (-not $streamUrl) { continue }
            Write-Log "Chronicle: $stream overridden to $streamUrl"
            $generatorArguments += @('--chronicle-stream-url', "$stream=$streamUrl")
          }
        }
        if ($ChronicleSince) { $generatorArguments += @('--chronicle-since', $ChronicleSince) }
        if ($ChronicleUser) { $generatorArguments += @('--chronicle-user', $ChronicleUser) }
      } else {
        # Not an error: this machine has never run the Copilot CLI, so there is no history to
        # replay. Said out loud so an empty chronicle dashboard has an explanation in the log.
        Write-Log "Chronicle: no store at $ChronicleDb, skipping (the Copilot CLI has not run here)" 'WARN'
      }
    }
    $output = & $Python '.\generate_dashboard.py' $generatorArguments 2>&1
    $code = $LASTEXITCODE
    $ErrorActionPreference = $previousPreference
  } finally {
    Pop-Location
  }

  foreach ($line in $output) { Write-Log $line.ToString() }

  if ($code -ne 0) {
    Write-Log "generate_dashboard.py exited with code $code" 'ERROR'
    exit $code
  }

  Write-Log 'Run completed.'
  exit 0
} finally {
  $env:OPENOBSERVE_PASSWORD = $null
  $env:OPENOBSERVE_USER = $null
  $env:COPILOT_PRICING_API_URL = $null
  $env:COPILOT_PRICING_CACHE_DAYS = $null
  if ($lock) { $lock.Dispose() }
}
