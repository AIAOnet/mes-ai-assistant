# Developer guide

## Setup

Use Python 3.13 and install the pinned packages from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
docker compose up -d --build
```

Copy `.env.example` to the ignored `.env` and replace its learning placeholders.
Generate the OPC UA and MQTT learning certificates using the commands in the
root [README](../README.md) before secure startup.

## Code map

See [Architecture](ARCHITECTURE.md). Keep physical behavior in `machine`,
transport adapters in `opc`/`mes`, domain decisions in `mes`, persistence in
`database`, and orchestration/UI boundaries in `dashboard`. `config/settings.json`
is the persisted non-secret runtime configuration; secrets stay in environment
variables.

## Tests and validation

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --check dashboard/app.js
docker compose config --quiet
.\scripts\production-readiness.ps1
```

Relevant suites cover machine/PLC behavior, OPC subscription delivery, MES rule
state, alarm/task lifecycle, SQL-facing controller behavior, production/OEE,
MQTT security, authentication, structured logging, metrics and alerts.

For database recovery changes, also run:

```powershell
.\scripts\backup-database.ps1
.\scripts\test-database-recovery.ps1 -BackupPath <new-backup.bak>
```

## API and authorization

FastAPI derives request validation from Pydantic models in `dashboard/api.py`.
Do not document or consume a route not declared there. Authentication uses the
`mes_session` signed cookie. Admin-only exact paths are `/api/config`,
`/api/security`, `/api/database`, `/api/diagnostics`, `/api/monitoring`, and
`/api/system/restart`; other `/api` operations require any authenticated role
when authentication is enabled.

## Change guidance

- Threshold semantic changes require synchronized settings, rules, UI and tests.
- Tag changes require PLC, transport subscription/topic, processor, persistence,
  UI and trace updates.
- Schema scripts must remain idempotent because `database-init` runs at startup.
- Never commit `.env`, private certificates, broker passwords or backups.
- Preserve correlation logging, redaction and bounded metric cardinality.
