[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Set-Location $projectRoot
$failures = [System.Collections.Generic.List[string]]::new()

function Check([bool]$Condition, [string]$Label) {
    if ($Condition) { Write-Output "PASS  $Label" } else { Write-Output "FAIL  $Label"; $failures.Add($Label) }
}

$environment = @{}
Get-Content -LiteralPath '.env' | ForEach-Object {
    if ($_ -match '^([^#=]+)=(.*)$') { $environment[$matches[1].Trim()] = $matches[2].Trim() }
}

Check (($environment['MES_DASHBOARD_SECRET']).Length -ge 32) 'Dashboard signing secret is at least 32 characters'
Check ([bool]($environment['MES_ADMIN_USERNAME'] -and $environment['MES_ADMIN_PASSWORD'])) 'Administrator credentials are configured'
Check ([bool]($environment['MES_OPERATOR_USERNAME'] -and $environment['MES_OPERATOR_PASSWORD'])) 'Operator credentials are configured'
Check ([bool]$environment['MES_SQL_PASSWORD']) 'SQL password is configured'
Check ([bool]$environment['MES_MQTT_PASSWORD']) 'MQTT password is configured'
$trackedSecrets = git -c safe.directory=$projectRoot ls-files .env certs mqtt/passwords backups
Check ($LASTEXITCODE -eq 0 -and ($trackedSecrets | Measure-Object).Count -eq 0) 'Runtime secrets and backups are not tracked by Git'

$requiredCertificates = @('certs/opc/client.der','certs/opc/client.pem','certs/opc/server.der','certs/opc/server.pem','certs/mqtt/mqtt-ca.crt','certs/mqtt/mqtt-client.crt','certs/mqtt/mqtt-client.key','certs/mqtt/mqtt-server.crt','certs/mqtt/mqtt-server.key')
Check (-not ($requiredCertificates | Where-Object { -not (Test-Path -LiteralPath $_) })) 'OPC UA and MQTT certificate files are present'

docker compose config --quiet
Check ($LASTEXITCODE -eq 0) 'Docker Compose configuration is valid'
foreach ($container in @('mes-sql-server','mes-mqtt-broker','mes-dashboard')) {
    $health = docker inspect $container --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' 2>$null
    Check ($health -eq 'healthy') "$container is healthy"
}

try {
    $healthResponse = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/healthz' -TimeoutSec 5
    Check ($healthResponse.StatusCode -eq 200) 'Dashboard readiness endpoint returns HTTP 200'
    Check ($healthResponse.Headers['X-Content-Type-Options'] -contains 'nosniff') 'Browser security headers are enabled'
} catch {
    Check $false 'Dashboard readiness endpoint returns HTTP 200'
}
try {
    $metrics = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/metrics' -TimeoutSec 5
    Check ($metrics.Content.Contains('mes_service_up')) 'Prometheus metrics are available'
} catch {
    Check $false 'Prometheus metrics are available'
}

$backup = Get-ChildItem -LiteralPath 'backups' -Filter 'MesSimulator-*.bak' -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Check ([bool]$backup) 'At least one database backup exists'

if ($failures.Count) {
    Write-Output "`nNOT READY: $($failures.Count) required check(s) failed."
    exit 1
}
Write-Output "`nREADY: all production-readiness checks passed."
