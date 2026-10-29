# Starts local SQL Server in Docker and runs sql/schema.sql and sql/seed.sql against database "orders".
# Safe to run repeatedly: this is the local stand-in for WS2's post-provision hook (Build Guide Phase 2 and 7).
$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $RepoRoot '.env'
$SqlCmd = '/opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -C -b'
$ReadyTimeoutSeconds = 90

function New-LocalPassword {
    # SQL Server needs upper, lower, digit and symbol; avoid ; } ! (connection-string breakers)
    $hex = -join ((1..16) | ForEach-Object { '{0:x}' -f (Get-Random -Maximum 16) })
    return "Ld#$($hex)Z9"
}

function Initialize-EnvFile {
    if (Test-Path $EnvFile) { return }
    "LOCAL_SA_PASSWORD=$(New-LocalPassword)" | Out-File -FilePath $EnvFile -Encoding ascii
    Write-Output "Created $EnvFile with a generated local SA password (git-ignored)."
}

function Invoke-Sql([string]$Arguments) {
    # The password never leaves the container: sqlcmd reads it from SQLCMDPASSWORD set from the container's env
    docker compose exec -T sql bash -c "SQLCMDPASSWORD=`"`$MSSQL_SA_PASSWORD`" $SqlCmd $Arguments"
    if ($LASTEXITCODE -ne 0) { throw "sqlcmd failed (exit $LASTEXITCODE): $Arguments" }
}

function Wait-SqlReady {
    $deadline = (Get-Date).AddSeconds($ReadyTimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        docker compose exec -T sql bash -c "SQLCMDPASSWORD=`"`$MSSQL_SA_PASSWORD`" $SqlCmd -Q 'SELECT 1'" *> $null
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
    Invoke-Sql "-Q `"IF DB_ID('orders') IS NULL CREATE DATABASE orders`""
    Invoke-Sql '-d orders -i /sql/schema.sql'
    Invoke-Sql '-d orders -i /sql/seed.sql'
    Invoke-Sql "-d orders -W -Q `"SET NOCOUNT ON; SELECT sku, name, price FROM dbo.products ORDER BY sku; SELECT name FROM sys.tables ORDER BY name; SELECT name FROM sys.indexes WHERE name = 'ix_orders_drill_id'`""
    Write-Output 'Local SQL ready: schema and seed applied.'
}
finally {
    Pop-Location
}
