# Operations runbook

## Start and verify

```powershell
docker compose up -d --build
docker compose ps
.\scripts\production-readiness.ps1
```

Expected long-running containers are `mes-sql-server`, `mes-mqtt-broker`, and
`mes-dashboard`, all healthy. `mes-database-init` should exit successfully.
The default host endpoints bind to `127.0.0.1` on ports 1433, 8883 and 8000.

## Diagnose

```powershell
docker compose ps
docker compose logs --tail 200 dashboard
docker compose logs --tail 200 mqtt-broker
docker compose logs --tail 200 sql-server
```

Check `/healthz`, then sign in as an administrator and inspect Diagnostics.
Correlate a client call with logs by supplying `X-Request-ID`. `/metrics` exposes
service availability, request counts/durations and active-alert count.

## Restart

Administrators can use Restart dashboard. From the host:

```powershell
docker compose restart dashboard
```

Wait for `docker compose ps` to report healthy. Restart does not preserve
in-memory metrics, recent errors, traces, or all runtime domain objects.

## Backup and recovery

```powershell
.\scripts\backup-database.ps1
.\scripts\test-database-recovery.ps1 -BackupPath .\backups\MesSimulator-YYYYMMDD-HHMMSS.bak
```

The backup script uses SQL checksums, `RESTORE VERIFYONLY`, SHA-256 output and
14-day retention by default. The recovery drill restores to a disposable
database and removes it. A production restore replaces `MesSimulator` and is
therefore explicitly guarded:

```powershell
.\scripts\restore-database.ps1 -BackupPath .\backups\MesSimulator-YYYYMMDD-HHMMSS.bak -ConfirmRestore
```

Perform replacement restore only in an approved maintenance window. Back up
`.env`, `config`, `certs`, and `mqtt/passwords` separately using encrypted,
off-host storage.

## Escalation criteria

Escalate when SQL or the selected transport remains unavailable, readiness does
not recover after restart, repeated API-failure alerts persist, recovery testing
fails, or certificates/credentials are missing or expired. Site owners must
supply contacts, severity targets, RTO/RPO, backup destination, alert routing,
maintenance windows and certificate-rotation schedule.
