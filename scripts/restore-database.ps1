[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$BackupPath,
    [switch]$ConfirmRestore
)

$ErrorActionPreference = 'Stop'
$container = 'mes-sql-server'
$database = 'MesSimulator'
$resolvedBackup = (Resolve-Path -LiteralPath $BackupPath).Path

if (-not $ConfirmRestore) {
    throw 'Restore replaces the MesSimulator database. Run again with -ConfirmRestore after checking the backup path.'
}
if ([System.IO.Path]::GetExtension($resolvedBackup) -ne '.bak') {
    throw 'BackupPath must identify a .bak file.'
}
if ((docker inspect --format '{{.State.Running}}' $container 2>$null) -ne 'true') {
    throw "Container '$container' is not running. Start it with: docker compose up -d"
}

$containerPath = '/var/opt/mssql/backup/restore-input.bak'
docker exec $container mkdir -p /var/opt/mssql/backup
docker cp $resolvedBackup "${container}:$containerPath"
if ($LASTEXITCODE -ne 0) { throw 'Could not copy the backup into the SQL container.' }

try {
    $restoreSql = "RESTORE VERIFYONLY FROM DISK = N'$containerPath' WITH CHECKSUM; ALTER DATABASE [$database] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; RESTORE DATABASE [$database] FROM DISK = N'$containerPath' WITH REPLACE, CHECKSUM; ALTER DATABASE [$database] SET MULTI_USER;"
    docker exec $container bash -lc 'SQLCMDPASSWORD="$MSSQL_SA_PASSWORD" /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -C -b -d master -Q "$1"' -- $restoreSql
    if ($LASTEXITCODE -ne 0) { throw 'SQL Server restore failed.' }
    Write-Output "Restore complete: $database"
    Write-Output 'Restarting the dashboard so all database connections are refreshed...'
    docker compose restart dashboard
    if ($LASTEXITCODE -ne 0) { throw 'Database restored, but the dashboard restart failed.' }
}
finally {
    $multiUserSql = "IF DB_ID(N'$database') IS NOT NULL ALTER DATABASE [$database] SET MULTI_USER"
    docker exec $container bash -lc 'SQLCMDPASSWORD="$MSSQL_SA_PASSWORD" /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -C -d master -Q "$1"' -- $multiUserSql 2>$null | Out-Null
    docker exec $container rm -f $containerPath 2>$null
}
