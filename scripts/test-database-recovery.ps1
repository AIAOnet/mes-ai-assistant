[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$BackupPath
)

$ErrorActionPreference = 'Stop'
$container = 'mes-sql-server'
$resolvedBackup = (Resolve-Path -LiteralPath $BackupPath).Path
$containerPath = '/var/opt/mssql/backup/recovery-test.bak'
$testDatabase = 'MesSimulatorRecoveryCheck'

if ([System.IO.Path]::GetExtension($resolvedBackup) -ne '.bak') { throw 'BackupPath must identify a .bak file.' }
if ((docker inspect --format '{{.State.Running}}' $container 2>$null) -ne 'true') { throw "Container '$container' is not running." }

docker exec $container mkdir -p /var/opt/mssql/backup
docker cp $resolvedBackup "${container}:$containerPath"
if ($LASTEXITCODE -ne 0) { throw 'Could not copy the backup into the SQL container.' }

try {
    $sql = "IF DB_ID(N'$testDatabase') IS NOT NULL BEGIN ALTER DATABASE [$testDatabase] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE [$testDatabase]; END; RESTORE VERIFYONLY FROM DISK = N'$containerPath' WITH CHECKSUM; RESTORE DATABASE [$testDatabase] FROM DISK = N'$containerPath' WITH MOVE N'MesSimulator' TO N'/var/opt/mssql/data/$testDatabase.mdf', MOVE N'MesSimulator_log' TO N'/var/opt/mssql/data/${testDatabase}_log.ldf', CHECKSUM; IF NOT EXISTS (SELECT 1 FROM sys.databases WHERE name = N'$testDatabase' AND state_desc = N'ONLINE') THROW 51000, 'Recovery database is not online', 1; ALTER DATABASE [$testDatabase] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE [$testDatabase];"
    docker exec $container bash -lc 'SQLCMDPASSWORD="$MSSQL_SA_PASSWORD" /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -C -b -d master -Q "$1"' -- $sql
    if ($LASTEXITCODE -ne 0) { throw 'Recovery verification failed.' }
    Write-Output 'Recovery verification: PASSED'
    Write-Output 'Temporary recovery database removed.'
}
finally {
    $cleanupSql = "IF DB_ID(N'$testDatabase') IS NOT NULL BEGIN ALTER DATABASE [$testDatabase] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE [$testDatabase]; END"
    docker exec $container bash -lc 'SQLCMDPASSWORD="$MSSQL_SA_PASSWORD" /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -C -b -d master -Q "$1"' -- $cleanupSql 2>$null | Out-Null
    docker exec $container rm -f $containerPath 2>$null
}
