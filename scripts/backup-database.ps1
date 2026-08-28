[CmdletBinding()]
param(
    [ValidateRange(1, 3650)]
    [int]$RetentionDays = 14,
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '..\backups')
)

$ErrorActionPreference = 'Stop'
$container = 'mes-sql-server'
$database = 'MesSimulator'
$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$fileName = "$database-$timestamp.bak"
$containerPath = "/var/opt/mssql/backup/$fileName"
$outputDirectoryPath = [System.IO.Path]::GetFullPath($OutputDirectory)
$outputPath = Join-Path $outputDirectoryPath $fileName

if ((docker inspect --format '{{.State.Running}}' $container 2>$null) -ne 'true') {
    throw "Container '$container' is not running. Start it with: docker compose up -d"
}

New-Item -ItemType Directory -Path $outputDirectoryPath -Force | Out-Null
docker exec $container mkdir -p /var/opt/mssql/backup
if ($LASTEXITCODE -ne 0) { throw 'Could not prepare the container backup directory.' }

$backupSql = "BACKUP DATABASE [$database] TO DISK = N'$containerPath' WITH COPY_ONLY, CHECKSUM, COMPRESSION, INIT; RESTORE VERIFYONLY FROM DISK = N'$containerPath' WITH CHECKSUM;"
docker exec $container bash -lc 'SQLCMDPASSWORD="$MSSQL_SA_PASSWORD" /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -C -b -Q "$1"' -- $backupSql
if ($LASTEXITCODE -ne 0) { throw 'SQL Server backup or integrity verification failed.' }

docker cp "${container}:$containerPath" $outputPath
if ($LASTEXITCODE -ne 0) { throw 'Could not copy the backup from the SQL container.' }
docker exec $container rm -f $containerPath

$cutoff = (Get-Date).AddDays(-$RetentionDays)
$expired = Get-ChildItem -LiteralPath $outputDirectoryPath -Filter 'MesSimulator-*.bak' -File | Where-Object LastWriteTime -lt $cutoff
foreach ($item in $expired) {
    Remove-Item -LiteralPath $item.FullName -Force
}

$hash = (Get-FileHash -LiteralPath $outputPath -Algorithm SHA256).Hash
Write-Output "Backup created: $outputPath"
Write-Output "SHA256: $hash"
Write-Output "Integrity: VERIFIED"
Write-Output "Expired backups removed: $($expired.Count)"
