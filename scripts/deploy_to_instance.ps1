param(
    [Parameter(Mandatory=$true)][string]$KeyPath,
    [Parameter(Mandatory=$true)][string]$RemoteHost,
    [string]$User = "ubuntu",
    [string]$RemotePath = "~/allora-forge-builder-kit",
    [string]$EnvPath = "",
    [switch]$Setup,
    [switch]$StartPoller,
    [int]$CadenceSeconds = 3600,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
function TS() { (Get-Date -Format "yyyy-MM-ddTHH:mm:ssK") }
function Log($msg) { Write-Host "[$(TS)] $msg" }

function Test-Command($name) {
  try { $null = Get-Command $name -ErrorAction Stop; return $true } catch { return $false }
}

# Resolve repo root
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot ".."))
Set-Location $RepoRoot
Log "[INFO] Repo: $RepoRoot"

if (-not (Test-Path $KeyPath)) { throw "KeyPath not found: $KeyPath" }
if (-not (Test-Command ssh)) { throw "ssh is not available in PATH" }
if (-not (Test-Command scp)) { throw "scp is not available in PATH" }

# Build SSH target
$Target = if ($User) { "{0}@{1}" -f $User, $RemoteHost } else { $RemoteHost }
Log "[INFO] Target: $Target RemotePath=$RemotePath"

# Ensure remote directory exists
& ssh -i $KeyPath $Target "mkdir -p $RemotePath" | Write-Host

# Create a tarball of the repo excluding items from .deployignore and stream to remote
$DeployIgnore = Join-Path $RepoRoot ".deployignore"
if (-not (Test-Path $DeployIgnore)) { Log "[WARN] .deployignore not found; proceeding without excludes" }

# Prefer BSD tar on Windows (tar.exe); if unavailable, fallback to Compress-Archive + scp
$TarAvailable = Test-Command tar

if ($TarAvailable) {
    Log "[INFO] Syncing files via tar archive + scp"
    $tarball = Join-Path $env:TEMP "repo_deploy.tar.gz"
    if (Test-Path $tarball) { Remove-Item $tarball -Force }
    $ExcludeArgs = @()
    if (Test-Path $DeployIgnore) {
        foreach ($line in (Get-Content -Raw -Encoding UTF8 $DeployIgnore).Split([Environment]::NewLine)) {
            $p = $line.Trim()
            if ($p -and -not $p.StartsWith('#')) { $ExcludeArgs += @("--exclude", $p) }
        }
    }
    # Build tar command to archive current directory
    $tarArgs = @('tar','-czf', $tarball) + $ExcludeArgs + @('.')
    Log ("[INFO] Running: {0}" -f ($tarArgs -join ' '))
    & $tarArgs[0] $tarArgs[1..($tarArgs.Count-1)] | Write-Host
    $dest = ("{0}:{1}/" -f $Target, $RemotePath)
    & scp -i $KeyPath $tarball $dest
    $remoteExtract = @(
        "cd $RemotePath",
        'tar -xzf repo_deploy.tar.gz',
        'rm -f repo_deploy.tar.gz'
    ) -join ' && '
    & ssh -i $KeyPath $Target $remoteExtract
    try { if (Test-Path $tarball) { Remove-Item $tarball -Force } } catch {}
} else {
    Log "[INFO] tar not available; falling back to Compress-Archive + scp"
    $zip = Join-Path $env:TEMP "repo_deploy.zip"
    if (Test-Path $zip) { Remove-Item $zip -Force }
    Compress-Archive -Path * -DestinationPath $zip -Force
    $dest = ("{0}:{1}/" -f $Target, $RemotePath)
    & scp -i $KeyPath $zip $dest
    $remoteUnzip = @(
        "cd $RemotePath",
        'if ! command -v unzip >/dev/null 2>&1; then sudo apt-get update -y && sudo apt-get install -y unzip; fi',
        'unzip -o repo_deploy.zip',
        'rm -f repo_deploy.zip'
    ) -join ' && '
    & ssh -i $KeyPath $Target $remoteUnzip
}

# Optionally copy env file explicitly
if ($EnvPath -and (Test-Path $EnvPath)) {
    Log "[INFO] Copying env: $EnvPath -> $RemotePath/.env"
    $destEnv = ("{0}:{1}" -f $Target, (Join-Path $RemotePath ".env"))
    & scp -i $KeyPath $EnvPath $destEnv
}

if ($Setup.IsPresent) {
    Log "[INFO] Running remote setup (python venv + requirements)"
    $remoteSetup = @(
        'set -euo pipefail',
        "cd $RemotePath",
        'if command -v apt-get >/dev/null 2>&1; then sudo apt-get update -y && sudo apt-get install -y python3-venv python3-pip libgomp1; fi',
        'python3 -m venv .venv || true',
        'source .venv/bin/activate',
        'python -m pip install --upgrade pip',
        'python -m pip install -r requirements.txt'
    ) -join ' && '
    & ssh -i $KeyPath $Target $remoteSetup
}

if ($StartPoller.IsPresent) {
    Log "[INFO] Starting Linux poller in background (nohup)"
    $forceEnv = if ($Force.IsPresent) { 'FORCE_FLAG=1' } else { '' }
    $remotePollCmd = ('nohup bash -c "CADENCE_SECONDS={0} {1} ENV_PATH=.env ./scripts/poll_hourly.sh" >/dev/null 2>&1 &' -f $CadenceSeconds, $forceEnv)
    $remotePoll = @(
        'set -euo pipefail',
        "cd $RemotePath",
        $remotePollCmd
    ) -join ' && '
    & ssh -i $KeyPath $Target $remotePoll
    Log "[INFO] Poller launched. Check logs at $RemotePath/data/artifacts/logs/poller-linux.log"
}

Log "[INFO] Done"
