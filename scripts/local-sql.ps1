# Starts local SQL Server in Docker, runs sql/schema.sql and sql/seed.sql against database "orders", and creates the
# app's order_app login with a generated password kept in the git-ignored .local/secret.txt (ADR-005, ADR-012).
# Safe to run repeatedly: this is the local stand-in for WS2's post-provision hook (Build Guide Phase 2 and 7).
# Windows PowerShell 5.1 turns native stderr (docker progress, sqlcmd retries) into terminating errors under 'Stop',
# so every native call below checks $LASTEXITCODE explicitly instead.
$ErrorActionPreference = 'Continue'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $RepoRoot '.env'
$SqlCmd = '/opt/mssql-tools18/bin/sqlcmd'
$ReadyTimeoutSeconds = 300  # first start on a low-memory PC takes 3-4 minutes
$VerifyQuery = @'
SET NOCOUNT ON;
SELECT sku, name, price FROM dbo.products ORDER BY sku;
SELECT name AS table_name FROM sys.tables ORDER BY name;
SELECT name AS index_name FROM sys.indexes WHERE name = 'ix_orders_drill_id';
'@
$AppSecretFile = Join-Path $RepoRoot '.local\secret.txt'
# Same grants as WS2's post-provision hook gives the app in Azure (Build Guide Phase 7 step 3)
$AppUserQuery = @'
SET NOCOUNT ON;
IF SUSER_ID('order_app') IS NULL CREATE LOGIN order_app WITH PASSWORD = '$(APP_DB_PASSWORD)';
ELSE ALTER LOGIN order_app WITH PASSWORD = '$(APP_DB_PASSWORD)';
IF USER_ID('order_app') IS NULL CREATE USER order_app FOR LOGIN order_app;
GRANT SELECT, INSERT ON dbo.orders TO order_app;
GRANT SELECT, INSERT ON dbo.payment_authorizations TO order_app;
GRANT SELECT ON dbo.products TO order_app;
SELECT name AS app_login FROM sys.sql_logins WHERE name = 'order_app';
'@

function New-LocalPassword {
    # SQL Server needs upper, lower, digit and symbol; avoid ; } ! (connection-string breakers)
    $bytes = New-Object byte[] 12
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $hex = -join ($bytes | ForEach-Object { '{0:x2}' -f $_ })
    return "Ld#$($hex)Z9"
}

function Initialize-AppSecretFile {
    # The order service reads its DB password from this file (local stand-in for Key Vault, ADR-012).
    # Keep an existing generated password; replace anything else (missing, empty, or another value).
    if (Test-Path $AppSecretFile) {
        $current = (Get-Content $AppSecretFile -Raw -ErrorAction Stop).Trim()
        if ($current -match '^Ld#[0-9a-f]{24}Z9$') { return $current }
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $AppSecretFile) | Out-Null
    $password = New-LocalPassword
    $password | Out-File -FilePath $AppSecretFile -Encoding ascii -ErrorAction Stop
    Write-Host "Created $AppSecretFile with a generated local app password (git-ignored)."
    return $password
}

function Set-AppUser([string]$Password) {
    # sqlcmd treats environment variables as scripting variables, so $(APP_DB_PASSWORD) in the query is filled
    # in inside the container and the password never appears on a command line. ALTER keeps an existing login
    # in step with the file.
    $env:APP_DB_PASSWORD = $Password
    try {
        docker compose exec -T -e SQLCMDPASSWORD -e APP_DB_PASSWORD sql $SqlCmd -S localhost -U sa -C -b -W -d orders -Q $AppUserQuery
        if ($LASTEXITCODE -ne 0) { throw "sqlcmd failed (exit $LASTEXITCODE) creating the order_app user" }
    }
    finally {
        Remove-Item Env:APP_DB_PASSWORD -ErrorAction SilentlyContinue
    }
}

function Initialize-EnvFile {
    if (Test-Path $EnvFile) { return }
    "LOCAL_SA_PASSWORD=$(New-LocalPassword)" | Out-File -FilePath $EnvFile -Encoding ascii -ErrorAction Stop
    Write-Output "Created $EnvFile with a generated local SA password (git-ignored)."
}

function Set-SqlCmdPassword {
    # sqlcmd reads SQLCMDPASSWORD; "-e SQLCMDPASSWORD" (name only) copies it from this process, so the password
    # never appears on a command line. No bash -c and no stdin pipe: PowerShell 5.1 mangles nested quotes and
    # prefixes piped text with a byte-order mark that SQL Server rejects.
    $line = Get-Content $EnvFile | Where-Object { $_ -like 'LOCAL_SA_PASSWORD=*' } | Select-Object -First 1
    if (-not $line) { throw "LOCAL_SA_PASSWORD missing from $EnvFile" }
    $env:SQLCMDPASSWORD = $line.Substring('LOCAL_SA_PASSWORD='.Length)
}

function Invoke-SqlCmd([string]$Database, [string]$Query, [string]$File) {
    $source = if ($File) { @('-i', $File) } else { @('-Q', $Query) }
    docker compose exec -T -e SQLCMDPASSWORD sql $SqlCmd -S localhost -U sa -C -b -W -d $Database @source
}

function Invoke-Sql([string]$Database, [string]$Query, [string]$File) {
    Invoke-SqlCmd -Database $Database -Query $Query -File $File
    if ($LASTEXITCODE -ne 0) { throw "sqlcmd failed (exit $LASTEXITCODE) on database ${Database}$(if ($File) { " running $File" })" }
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
    Set-SqlCmdPassword
    docker compose up -d sql
    if ($LASTEXITCODE -ne 0) { throw 'docker compose up failed. Is Docker Desktop running?' }
    Wait-SqlReady
    Invoke-Sql -Database 'master' -Query "IF DB_ID('orders') IS NULL CREATE DATABASE orders"
    Invoke-Sql -Database 'orders' -File '/sql/schema.sql'
    Invoke-Sql -Database 'orders' -File '/sql/seed.sql'
    Invoke-Sql -Database 'orders' -Query $VerifyQuery
    Set-AppUser -Password (Initialize-AppSecretFile)
    Write-Output 'Local SQL ready: schema and seed applied, order_app user in place.'
}
finally {
    Remove-Item Env:SQLCMDPASSWORD -ErrorAction SilentlyContinue
    Pop-Location
}
