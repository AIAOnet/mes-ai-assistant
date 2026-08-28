# Operator guide

## Sign in and roles

Open `http://127.0.0.1:8000` and use the account supplied by the deployment
owner. The implemented roles are `operator` and `admin`. Both authenticated
roles can operate the simulation, machine, faults, alarms, tasks, production
orders and communication mode. Only `admin` can open Configuration, Security,
Diagnostics and Database data or restart the dashboard. Authentication routes
and static content remain available to sign in.

## Normal workflow

1. Confirm the connection indicator is online and Overview values update.
2. Start or pause the simulation as needed. Simulation pause stops ticks; it is
   distinct from stopping the machine.
3. Use machine Start, Stop and Reset. Reset restores normal simulated conditions.
4. In Production, create a unique order ID, product name and positive target.
   Start one order at a time; record rejects or complete the order manually.
5. Review active alarms. Acknowledgement records the supplied operator name but
   does not resolve the condition.
6. In Maintenance Tasks, start an `OPEN` task and complete it only after it is
   `IN_PROGRESS`.

## Fault exercises

Pressure and temperature fault buttons change the physical simulation. They do
not create alarms directly. The value must cross the configured critical
threshold through the selected communication path before the MES emits a
condition-entered event. Recovery and alarm resolution occur only after the
value falls below the warning/recovery threshold.

## Communication and data flow

The Communication tab selects OPC UA or MQTT and shows connection information.
The Data Flow tab visualizes recent trace steps; it is explanatory state held in
memory, not a replacement for SQL history or logs.

## Admin tasks

- Configuration changes thresholds, intervals and endpoints. A returned
  `restart_required` state is shown when endpoint/transport addressing changes.
- Security changes dashboard, OPC UA and MQTT settings and require restart.
- Diagnostics shows dependency state, request measurements, alerts and recent
  redacted application errors.
- Database is a read-only latest-50 view.
- Restart dashboard waits for the service to return and reloads the page.

For incident steps, use the [Operations runbook](OPERATIONS_RUNBOOK.md).
