param(
    [string]$TopicId = "67",
    [string]$RPC = "https://allora-rpc.testnet.allora.network/"
)

$ErrorActionPreference = "Continue"

# Ensure UTF-8 output to avoid mojibake for emoji/non-ASCII on Windows PowerShell
try {
    $enc = [System.Text.Encoding]::UTF8
    [Console]::OutputEncoding = $enc
    # Affects external program output encoding (e.g., allorad)
    $OutputEncoding = New-Object System.Text.UTF8Encoding $false
} catch { }

function Normalize-Rpc([string]$rpc) {
    if ([string]::IsNullOrWhiteSpace($rpc)) { return $rpc }
    $first = ($rpc -split "\s+")[0]
    if ($first -match '^(https?://[^/\s]+)') { return $Matches[1] }
    if ($first -match '^(tcp://[^/\s]+)') { return $Matches[1] }
    return $first
}
$RPC = Normalize-Rpc $RPC

if (-not $env:ALLORA_WALLET_ADDR -or [string]::IsNullOrWhiteSpace($env:ALLORA_WALLET_ADDR)) {
    Write-Error "ALLORA_WALLET_ADDR is not set. Set it first, e.g.: `$env:ALLORA_WALLET_ADDR = 'allo...'"; exit 1
}

$ts = Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"
Write-Host "[$ts] Checking Allora worker status"
Write-Host "Wallet: $($env:ALLORA_WALLET_ADDR) | Topic: $TopicId | RPC: $RPC"

# 0) Can submit worker payload now?
try {
    $ts0 = Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"
    Write-Host "[$ts0] Query: can-submit-worker-payload"
    $canRaw = & allorad query emissions can-submit-worker-payload $TopicId $env:ALLORA_WALLET_ADDR --node $RPC -o json 2>$null
    if ($LASTEXITCODE -eq 0 -and $canRaw) {
        $can = $false
        try {
            $canObj = $canRaw | ConvertFrom-Json
            if ($canObj -is [bool]) { $can = [bool]$canObj }
            elseif ($canObj -is [string]) { if ($canObj.ToLower().Contains('true')) { $can = $true } }
            elseif ($canObj.result -ne $null) { if ("$($canObj.result)".ToLower().Contains('true')) { $can = $true } }
        } catch { if ($canRaw.ToLower().Contains('true')) { $can = $true } }
        if ($can) { Write-Host "[$ts0] Can submit now: TRUE" } else { Write-Host "[$ts0] Can submit now: FALSE (likely out of window)" }
    } else {
        Write-Warning "[$ts0] can-submit-worker-payload query failed (exit $LASTEXITCODE)."
    }
} catch { Write-Warning "can-submit-worker-payload error: $_" }

# 1) Worker Info (nonce)
try {
    $ts1 = Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"
    Write-Host "[$ts1] Query: worker-info"
    $infoRaw = & allorad query emissions worker-info $env:ALLORA_WALLET_ADDR --node $RPC -o json 2>$null
    if ($LASTEXITCODE -eq 0 -and $infoRaw) {
        $nonceVal = $null
        try {
            $infoObj = $infoRaw | ConvertFrom-Json
            if ($infoObj.nonce) { $nonceVal = $infoObj.nonce }
            elseif ($infoObj.worker -and $infoObj.worker.nonce) { $nonceVal = $infoObj.worker.nonce }
            elseif ($infoObj.data -and $infoObj.data.nonce) { $nonceVal = $infoObj.data.nonce }
        } catch {
            if ($infoRaw -match '"nonce"\s*:\s*"?(?<nonce>[0-9]+)"?') { $nonceVal = $Matches['nonce'] }
        }
        if ($nonceVal) {
            Write-Host "[$ts1] worker-info nonce: $nonceVal  ✅ Submission processed"
        } else {
            Write-Host "[$ts1] worker-info fetched but nonce not found. 🟡 Waiting for fulfillment…"
        }
    } else {
        Write-Warning "[$ts1] worker-info query failed (exit $LASTEXITCODE)."
    }
} catch { Write-Warning "worker-info error: $_" }

# 2) Unfulfilled worker nonces
try {
    $ts2 = Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"
    Write-Host "[$ts2] Query: unfulfilled-worker-nonces"
    $ufRaw = & allorad query emissions unfulfilled-worker-nonces $TopicId --node $RPC -o json 2>$null
    if ($LASTEXITCODE -eq 0 -and $ufRaw) {
        $hasPending = $false
        try {
            $ufObj = $ufRaw | ConvertFrom-Json
            if ($ufObj -is [System.Array]) { if ($ufObj.Count -gt 0) { $hasPending = $true } }
            elseif ($ufObj -and $ufObj.Count -gt 0) { $hasPending = $true }
        } catch { if ($ufRaw -notmatch "\[\s*\]") { $hasPending = $true } }
        if ($hasPending) {
            Write-Host "[$ts2] Unfulfilled worker nonces (topic $TopicId): $ufRaw"
            Write-Host "[$ts2] 🟡 Waiting for fulfillment…"
        } else {
            Write-Host "[$ts2] No unfulfilled worker nonces for topic $TopicId."
        }
    } else {
        Write-Warning "[$ts2] unfulfilled-worker-nonces query failed (exit $LASTEXITCODE)."
    }
} catch { Write-Warning "unfulfilled-worker-nonces error: $_" }

# 3) Latest worker inference
try {
    $ts3 = Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"
    Write-Host "[$ts3] Query: worker-latest-inference"
    $latestRaw = & allorad query emissions worker-latest-inference $TopicId $env:ALLORA_WALLET_ADDR --node $RPC -o json 2>$null
    if ($LASTEXITCODE -eq 0 -and $latestRaw) {
        Write-Host "[$ts3] worker-latest-inference: $latestRaw"
    } else {
        Write-Host "[$ts3] No worker-latest-inference visible yet. 🟡 Waiting for fulfillment…"
    }
} catch { Write-Warning "worker-latest-inference error: $_" }

Write-Host "Done."
