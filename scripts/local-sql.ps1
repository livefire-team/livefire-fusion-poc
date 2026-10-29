# Starts local SQL Server in Docker and runs sql/schema.sql and sql/seed.sql against database "orders".
# Safe to run repeatedly: this is the local stand-in for WS2's post-provision hook (Build Guide Phase 2 and 7).
# Windows PowerShell 5.1 turns native stderr (docker progress, sqlcmd retries) into terminating errors under 'Stop',
# so every native call below checks $LASTEXITCODE explicitly instead.
$ErrorActionPreference = 'Continue'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $RepoRoot '.env'
$SqlCmd = '/opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -C -b'
$ReadyTimeoutSeconds = 90
$VerifyQuery = @'
SET NOCOUNT ON;
SELECT sku, name, price FROM dbo.products ORDER BY sku;
SELECT name AS table_name FROM sys.tables ORDER BY name;
SELECT name AS index_name FROM sys.indexes WHERE name = 'ix_orders_drill_id';
'@

function New-LocalPassword {
    # SQL Server needs upper, lower, digit and symbol; avoid ; } ! (connection-string breakers)
    $hex = -join ((1..16) | ForEach-Object { '{0:x}' -f (Get-Random -Maximum 16) })
    return "Ld#$($hex)Z9"
}

function Initialize-EnvFile {
    if (Test-Path $EnvFile) { return }
    "LOCAL_SA_PASSWORD=$(New-LocalPassword)" | Out-File -FilePath $EnvFile -Encoding ascii -ErrorAction Stop
    Write-Output "Created $EnvFile with a generated local SA password (git-ignored)."
}

function Invoke-SqlCmd([string]$Database, [string]$Query, [string]$File) {
    # Queries go through stdin (-i /dev/stdin) so no quoting crosses PowerShell, docker and bash.
    # The password never leaves the container: sqlcmd reads SQLCMDPASSWORD set from the container's own env.
    # Some PowerShell hosts prefix piped text with a UTF-8 byte-order mark, which SQL Server rejects; sed strips it.
    $sqlcmd = "SQLCMDPASSWORD=`$MSSQL_SA_PASSWORD $SqlCmd -W -d $Database"
    if ($File) { docker compose exec -T sql bash -c "$sqlcmd -i $File" }
    else { $Query | docker compose exec -T sql bash -c "sed '1s/^\xEF\xBB\xBF//' | $sqlcmd -i /dev/stdin" }
}

function Invoke-Sql([string]$Database, [string]$Query, [string]$File) {
    Invoke-SqlCmd -Database $Database -Query $Query -File $File
    if ($LASTEXITCODE -ne 0) { throw "sqlcmd failed (exit $LASTEXITCODE) on database ${Database}: $Query$File" }
}

function Wait-SqlReady {
    $deadline = (Get-Date).AddSeconds($ReadyTimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        Invoke-SqlCmd -Database 'master' -Query 'SELECT 1' *> $null
        if ($LASTEXITCODE -eq 0) { return }
        Start-Sleep -Seconds 3
    }
    throw "SQL Server was not ready after $ReadyTimeoutSeconds seconds. Check: docker compose logs sql"
}

Push-Location $RepoRoot
try {
    Initialize-EnvFile
    docker compose up -d sql
    if ($LASTEXITCODE -ne 0) { throw 'docker compose up failed. Is Docker Desktop running?' }
    Wait-SqlReady
    Invoke-Sql -Database 'master' -Query "IF DB_ID('orders') IS NULL CREATE DATABASE orders"
    Invoke-Sql -Database 'orders' -File '/sql/schema.sql'
    Invoke-Sql -Database 'orders' -File '/sql/seed.sql'
    Invoke-Sql -Database 'orders' -Query $VerifyQuery
    Write-Output 'Local SQL ready: schema and seed applied.'
}
finally {
    Pop-Location
}
