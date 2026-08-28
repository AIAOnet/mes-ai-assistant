# MES Factory Simulation

This project is a hands-on learning environment for the path:

```text
Machine -> PLC -> OPC UA / MQTT -> MES -> SQL Server -> Dashboard
```

Development is intentionally phased. Only move to the next phase after the
current phase works and its tests pass.

The maintained documentation set starts at [docs/README.md](docs/README.md),
including architecture, operator/developer guides, communication, configuration,
lifecycles, operations and requirements traceability.

## Phase 1: Machine and PLC tags

Run the simulation from the repository root:

```powershell
python -m machine
```

Run the tests:

```powershell
python -m unittest discover -s tests -v
```

## Phase 2: OPC UA subscriptions

Create the local environment and install the dependency once:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Open two terminals. Start the PLC-facing OPC UA server in the first:

```powershell
.\.venv\Scripts\python.exe -m opc.server
```

Start the learning client in the second:

```powershell
.\.venv\Scripts\python.exe -m opc.client
```

The client subscribes to `Machine01.Pressure`. It does not repeatedly ask for
the value. The OPC UA server sends a `DataChangeNotification` whenever the
published PLC value changes.

**OPC UA**

- Industrial meaning: a vendor-neutral protocol and information model used to
  exchange industrial data securely.
- Software analogy: a typed, browsable API designed for equipment data.

**OPC UA subscription**

- Industrial meaning: a client asks a server to monitor nodes and report data
  changes.
- Software analogy: registering an event listener instead of polling an API.

## Phase 3: MES event engine

With the OPC UA server running, start the MES in a second terminal:

```powershell
.\.venv\Scripts\python.exe -m mes.main
```

The MES subscribes to all six PLC tags. Pressure and temperature values enter
state-aware threshold rules. A condition creates one alarm when it becomes
active, no duplicate alarms while it remains active, and a recovery event when
it returns to a safe range.

Thresholds are configured in `config/settings.json`. The warning threshold is
also used as the recovery boundary, creating hysteresis:

```text
Pressure > 100  -> enter HIGH_PRESSURE
Pressure 90-100 -> keep the previous condition state
Pressure < 90   -> recover from HIGH_PRESSURE
```

**MES (Manufacturing Execution System)**

- Industrial meaning: the operational layer that tracks and coordinates
  production between plant controls and business systems.
- Software analogy: an event-driven business application for factory work.

**Alarm**

- Industrial meaning: a condition requiring operator awareness or action.
- Software analogy: a stateful domain record created when a rule transitions
  from normal to abnormal.

## Phase 4: SQL Server persistence

Start the SQL Server container:

```powershell
docker compose up -d sql-server
```

Initialize the database after SQL Server is ready:

```powershell
.\.venv\Scripts\python.exe -m database.bootstrap
```

The database contains `Machines`, `MachineReadings`, `Events`, `Alarms`,
`MaintenanceTasks`, `ProductionOrders`, and `ProductionRecords`. The MES writes
condition events and alarm state through `SQLServerRepository`.

`dbo.GetMachineAlarmHistory` demonstrates a stored procedure. The
`TR_Alarms_AuditStatusChange` trigger records alarm status changes in
`AlarmAudit`. Threshold and alarm-creation logic remains in Python because it
depends on ordered communication events and should be explicit and testable.
The trigger handles only a database-level audit concern.

The Compose password and old Windows ODBC driver configuration are for local
learning only. A production installation should use secret management,
Microsoft ODBC Driver 18, certificate validation, least-privilege database
accounts, and encrypted connections.

## Phase 5, step 1: Unified web interface

Make sure SQL Server is running, then start the complete learning environment:

```powershell
docker compose up -d sql-server
.\.venv\Scripts\python.exe -m dashboard.api
```

Open `http://127.0.0.1:8000`. This single process owns the machine simulator,
PLC tags, OPC UA server, MES subscription, rule engine, SQL repository, API,
WebSocket stream, and dashboard.

Simulation Run/Pause controls simulated time. Machine Start/Stop changes the
physical machine state. Fault buttons affect only the machine; any alarm still
has to travel through PLC tags, OPC UA, and MES rules.

### Dashboard configuration

The Configuration section edits pressure and temperature warning/critical
thresholds, simulation update interval, production cadence, and the OPC UA
endpoint. Threshold and timing changes apply immediately and are saved to
`config/settings.json`. An OPC endpoint change is saved but requires restarting
the web application because the server and client must be rebound safely.

The API rejects warning values that are not below their critical value and
rejects invalid timing ranges or non-OPC endpoint schemes. MQTT is displayed as
a future mode but remains disabled until Phase 7 implements that transport.

### Alarm acknowledgement and maintenance tasks

An active alarm can be acknowledged with an operator name. Acknowledgement only
records that an operator has seen the alarm; physical recovery remains the only
way an alarm becomes resolved.

`HIGH_PRESSURE` and `HIGH_TEMPERATURE` alarms automatically create one
maintenance task. Operators move tasks through `OPEN`, `IN_PROGRESS`, and
`COMPLETED` from the dashboard. Acknowledgement fields and task transitions are
persisted in SQL Server.

### Read-only Database tab

The Database tab provides a safe learning view of the latest 50 rows from
`MachineReadings`, `Events`, `Alarms`, `MaintenanceTasks`, `AlarmAudit`,
`ProductionOrders`, and `ProductionRecords`.
Use the left sidebar to display one table at a time. The row count beside each
table shows how much data was loaded, and **Live search** filters the selected
table immediately across all of its columns. The API uses fixed repository
queries rather than accepting arbitrary SQL. Select **Refresh database** to
retrieve the newest persisted rows.

## Phase 6: Production orders and OEE

The **Production** tab creates production orders with an order ID, product,
and target quantity. An operator starts one planned order at a time. New units
reported by the machine are automatically counted as good parts for the active
order, and the order completes automatically when it reaches its target.
Operators can reclassify a produced good part as rejected or complete an order
early.

The live OEE panel shows:

- **Availability:** operating time divided by elapsed order time.
- **Performance:** actual output compared with the configured ideal cycle.
- **Quality:** good parts divided by total produced parts.
- **OEE:** availability × performance × quality.

Order lifecycle changes and production-count snapshots are persisted in SQL
Server and can be inspected from the Database tab.

## Phase 7: OPC UA and MQTT communication

The **Communication** tab switches the live MES input between OPC UA and MQTT
without changing the event processor or business rules. MQTT uses the local
Mosquitto broker at `127.0.0.1:1883` and publishes changed PLC values beneath
`factory/machine-01/`. The tab shows the selected transport, its connection
state, the end-to-end data path, and the latest 30 MQTT messages.

Start the broker with:

```powershell
docker compose up -d mqtt-broker
```

The included broker permits anonymous access for local learning only. A real
deployment should enable authentication, authorization by topic, and TLS.

## Phase 8: Educational Data Flow monitor

The **Data Flow** tab visualizes every value handled by the MES as a trace:

`Machine → PLC tag → transport → MES processor → rule → event → alarm → task → SQL → dashboard`

Active stages are highlighted for the selected trace. When a rule produces no
state transition, the event, alarm, and task stages are dimmed. The selected
trace panel explains the exact tag/value, decision, outcome, persistence
tables, and processing latency. Select **Pause** to freeze the monitor, click
any timeline row to replay its path, then select **Return to live** to follow
new values again. The in-memory monitor retains the latest 100 traces and the
UI shows the latest 30.

## Phase 9: Security configuration and dashboard access

The **Security** tab collects and validates the settings required for later
security enforcement:

- Dashboard authentication, session timeout, and action auditing.
- OPC UA message security mode, policy, application certificate, private key,
  and trust-list paths.
- MQTT TLS, username, CA certificate, and optional client-certificate paths.

Passwords and session-signing secrets are deliberately excluded from the JSON
configuration and browser API. Supply them with `MES_MQTT_PASSWORD` and
`MES_DASHBOARD_SECRET`. Secured OPC UA modes require certificate and key paths;
MQTT TLS requires a CA certificate path. Saving security settings marks a
restart as required.

Dashboard authentication is enforced with signed, expiring, HTTP-only session
cookies when enabled. The `admin` role can open Security, Configuration, and
Database; the `operator` role can run the machine workflow and update alarms,
tasks, and production orders. Configuration remains in its own top-level tab.

Set a signing secret of at least 32 characters and at least one account before
enabling authentication. See `.env.example` for all account variables.
Authenticated API mutations are written to `OperatorActionAudit` when action
auditing is enabled. Re-run `python -m database.bootstrap` once to add that
table to an existing database.

MQTT is secured with a local CA, mutual TLS client certificates, and Mosquitto
username/password authentication on port `8883`. Generate the learning
certificates and password file before the first secure broker start:

```powershell
.\.venv\Scripts\python.exe -m mqtt.certificates
$mqttPassword=(Get-Content .env | Where-Object {$_ -match '^MES_MQTT_PASSWORD='} | Select-Object -First 1).Split('=',2)[1]
$mqttDir=(Resolve-Path '.\mqtt').Path
docker run --rm -v "${mqttDir}:/work" eclipse-mosquitto:2.0 mosquitto_passwd -b -c /work/passwords mes-client $mqttPassword
docker compose up -d --force-recreate mqtt-broker
```

Anonymous port `1883` is no longer exposed. The broker certificate is valid for
`localhost`, `127.0.0.1`, and the Compose service name `mqtt-broker`.
Antivirus products that intercept TLS must exclude `127.0.0.1:8883` from Web
or Mail Shield scanning; mutual TLS cannot work through a proxy that replaces
the server certificate and does not forward the client certificate.

### Concepts in this phase

**Machine simulator**

- Industrial meaning: a stand-in for physical equipment and sensors.
- Software analogy: an object whose state evolves over time.

**PLC (Programmable Logic Controller)**

- Industrial meaning: a rugged controller that reads machine signals and
  exposes controlled process values.
- Software analogy: an adapter between physical state and external systems.

**PLC tag**

- Industrial meaning: a named value available from the PLC, such as pressure.
- Software analogy: a typed field exposed through a stable interface.

The machine owns physical behavior. The PLC copies machine values into named
tags. Later, OPC UA and MQTT will publish those tags; neither protocol should
reach directly into the machine.

## Current assumptions

- One simulated machine, `MACHINE-01`.
- The simulation advances once per `tick`; the demo command uses one tick per
  second.
- A produced unit is counted every five running ticks.
- Fault controls affect only the physical simulation. They never create MES
  alarms directly.

## Phase 10, step 1: Containerized reliable startup

The complete application now starts with one command:

```powershell
docker compose up -d --build
```

Compose waits for SQL Server and the mutual-TLS MQTT broker to become healthy,
runs the idempotent database bootstrap, and then starts the dashboard at
`http://127.0.0.1:8000`. The dashboard image contains application code only;
`.env`, MQTT credentials, and OPC/MQTT certificates are mounted at runtime.

Inspect service health with:

```powershell
docker compose ps
```

The dashboard exposes unauthenticated `/healthz` readiness information for the
container health check. The admin **Restart dashboard** action exits the main
container process and Compose restarts it automatically.

## Phase 10, step 2: Structured logs and diagnostics

Application request logs are emitted as one-line JSON with a correlation ID,
HTTP status, duration, authenticated user and role, and client address. Supply
an `X-Request-ID` header to carry an existing correlation ID across a call;
otherwise the dashboard creates one and returns it in the response header.
Passwords, secrets, tokens, cookies, authorization values, and private-key
fields are redacted before logging.

The admin-only **Diagnostics** tab shows live SQL, OPC UA, MQTT, and dashboard
health; safe runtime/container metadata; uptime; and the latest 50 in-memory
application errors. Docker rotates each service's JSON logs at five 10 MB
files. Use `docker compose logs dashboard` for the structured stream.

## Phase 10, step 3: Monitoring and alerting

Prometheus-compatible metrics are available at `http://127.0.0.1:8000/metrics`.
They report dependency availability, HTTP request counts by method/path/status,
request-duration totals, and the number of active alerts. The endpoint has no
dashboard-session requirement so a collector can scrape it; expose it only on
a trusted operations network in production.

The admin **Diagnostics** tab also shows request totals, error rate, average and
95th-percentile response time, a recent latency trend, and active alerts. A
critical alert is raised when SQL Server or the selected transport is
unavailable. A warning is raised after three server failures occur within the
latest 20 requests.

## Phase 10, step 4: Backup and disaster recovery

Create a checksummed SQL Server backup with 14-day retention:

```powershell
.\scripts\backup-database.ps1
```

Backups are written to the ignored `backups` directory. Override retention with
`-RetentionDays 30`. Each run performs `RESTORE VERIFYONLY` and prints a SHA-256
hash. Prove that a backup can actually be recovered into a temporary database:

```powershell
.\scripts\test-database-recovery.ps1 -BackupPath .\backups\MesSimulator-YYYYMMDD-HHMMSS.bak
```

Restore the application database only during a maintenance window. The explicit
confirmation switch prevents an accidental overwrite; the dashboard restarts
afterward to refresh its connection pool:

```powershell
.\scripts\restore-database.ps1 -BackupPath .\backups\MesSimulator-YYYYMMDD-HHMMSS.bak -ConfirmRestore
```

Treat `.env`, `config`, `certs`, and `mqtt/passwords` as a separate encrypted
configuration backup. They contain credentials or private keys and must never be
stored in Git or beside unencrypted database backups. For recovery: restore those
files first, run `docker compose up -d`, restore the database, run the recovery
test, then confirm `docker compose ps` and the admin Diagnostics tab are healthy.

## Phase 10, step 5: Production readiness

Run the repeatable deployment audit with:

```powershell
.\scripts\production-readiness.ps1
```

The audit validates secrets are configured but untracked, required certificates
exist, Compose is valid, all containers are healthy, security headers and metrics
respond, and a database backup exists. See `PRODUCTION_READINESS.md` for the final
pilot decision, verified controls, deployment-owner actions, and accepted limits.
