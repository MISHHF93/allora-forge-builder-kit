param(
    [string]$Path = "..\.env"
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false) } catch {}

function Mask-Value([string]$v) {
    if ([string]::IsNullOrEmpty($v)) { return "" }
    if ($v.Length -le 6) { return "***" }
    return $v.Substring(0,3) + "***" + $v.Substring($v.Length-3)
}

# Resolve path relative to this script
$envPath = (Resolve-Path (Join-Path $PSScriptRoot $Path)).Path
if (-not (Test-Path $envPath)) {
    Write-Error "No .env found at $envPath"
}

$lines = Get-Content -LiteralPath $envPath -Encoding UTF8
$loaded = @{}
foreach ($raw in $lines) {
    $line = $raw.Trim()
    if (-not $line) { continue }
    if ($line.StartsWith('#')) { continue }
    if (-not ($line.Contains('='))) { continue }
    $kv = $line.Split('=',2)
    $key = $kv[0].Trim()
    $val = $kv[1].Trim().Trim('"').Trim("'")
    if (-not $key) { continue }
    Set-Item -Path "env:$key" -Value $val
    $loaded[$key] = $val
}

if ($loaded.Count -gt 0) {
    Write-Host "Loaded $($loaded.Count) env vars from ${envPath}:" 
    foreach ($k in $loaded.Keys) {
        $masked = Mask-Value $loaded[$k]
        Write-Host "  $k=$masked"
    }
} else {
    Write-Warning "No environment variables loaded from $envPath (file empty or only comments)."
}
