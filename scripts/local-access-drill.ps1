# Local access drill (Build Guide Phase 7 step 4) against the Docker Compose stack.
# Starts SQL and the order service, then walks four stages and records what the app reports at each one:
#   baseline         - normal running
#   access lost      - .local/secret.txt holds "forbidden", which the app's file source reads as a 403
#   access restored  - the real password is written back
#   after restart    - `docker compose restart orders`
# At each stage it calls GET /health, GET /health/dependencies and POST /api/orders (with an x-drill-id header)
# and prints one table row. The real password is always written back at the end.
# Exit code: 0 when every stage ran; 1 when the stack could not be started.
param(
    [string]$BaseUrl = 'http://127.0.0.1:8000',
    [string]$Sku = 'SKU-001',
    [int]$SettleSeconds = 10,          # longer than the stack's SECRET_REFRESH_SECONDS (2)
    [int]$StartTimeoutSeconds = 180
)
$ErrorActionPreference = 'Continue'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$SecretFile = Join-Path $RepoRoot '.local\secret.txt'
$RunId = Get-Date -Format 'yyyyMMddHHmmss'

function Invoke-Http([string]$Method, [string]$Path, [string]$Body, [hashtable]$Headers = @{}) {
    # Returns @{ Status; Body } for any HTTP answer; Status 0 when there was no answer at all.
    $params = @{ Uri = "$BaseUrl$Path"; Method = $Method; UseBasicParsing = $true; TimeoutSec = 30; Headers = $Headers }
    if ($Body) { $params.Body = $Body; $params.ContentType = 'application/json' }
    try {
        $r = Invoke-WebRequest @params
        return @{ Status = [int]$r.StatusCode; Body = $r.Content }
    }
    catch [System.Net.WebException] {
        # PowerShell 5.1 has already read the error body into ErrorDetails
        $resp = $_.Exception.Response
        if ($null -eq $resp) { return @{ Status = 0; Body = $_.Exception.Message } }
        $body = if ($_.ErrorDetails) { $_.ErrorDetails.Message } else { '' }
        return @{ Status = [int]$resp.StatusCode; Body = $body }
    }
}

function Wait-Health {
    $deadline = (Get-Date).AddSeconds($StartTimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if ((Invoke-Http -Method 'GET' -Path '/health').Status -eq 200) { return }
        Start-Sleep -Seconds 2
    }
    throw "/health did not answer 200 within $StartTimeoutSeconds seconds. Check: docker compose logs orders"
}

function Write-SecretFile([string]$Value) {
    # ASCII (no byte-order mark); the app trims the trailing newline
    $Value | Out-File -FilePath $SecretFile -Encoding ascii -ErrorAction Stop
}

function Measure-Stage([string]$Name) {
    $health = Invoke-Http -Method 'GET' -Path '/health'
    $deps = Invoke-Http -Method 'GET' -Path '/health/dependencies'
    $drillId = "local-$RunId-$($Name -replace '[^A-Za-z0-9]', '-')"
    $order = Invoke-Http -Method 'POST' -Path '/api/orders' -Body (@{ sku = $Sku } | ConvertTo-Json -Compress) `
        -Headers @{ 'x-drill-id' = $drillId }
    [pscustomobject]@{
        'stage'        = $Name
        '/health'      = $health.Status
        'dependencies' = "$($deps.Status) $($deps.Body)"
        'order result' = "$($order.Status) $($order.Body)"
    }
}

function Start-Stack {
    & (Join-Path $PSScriptRoot 'local-sql.ps1')
    if (-not $?) { throw 'local-sql.ps1 failed' }
    docker compose up -d --build orders
    if ($LASTEXITCODE -ne 0) { throw 'docker compose up orders failed' }
    Wait-Health
}

Push-Location $RepoRoot
$password = $null
$rows = @()
try {
    try {
        Start-Stack
        $password = (Get-Content $SecretFile -Raw -ErrorAction Stop).Trim()
    }
    catch {
        Write-Error "Stack did not start: $_"
        exit 1
    }

    $rows += Measure-Stage 'baseline'

    Write-SecretFile 'forbidden'
    Start-Sleep -Seconds $SettleSeconds
    $rows += Measure-Stage 'access lost'

    Write-SecretFile $password
    Start-Sleep -Seconds $SettleSeconds
    $rows += Measure-Stage 'access restored'

    docker compose restart orders
    Wait-Health
    $rows += Measure-Stage 'after restart'
    exit 0
}
finally {
    if ($password) { Write-SecretFile $password }
    if ($rows.Count -gt 0) { $rows | Format-Table -AutoSize -Wrap | Out-String -Width 220 | Write-Output }
    Pop-Location
}
