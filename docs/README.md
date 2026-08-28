# MES documentation

This documentation describes the implementation in this repository. The root
[README](../README.md) remains the phased build specification and quick-start
history.

| Document | Audience | Purpose |
| --- | --- | --- |
| [Architecture](ARCHITECTURE.md) | Technical leads | Components, boundaries, runtime and data flow |
| [Operator guide](OPERATOR_GUIDE.md) | Operators and administrators | Dashboard workflows and role boundaries |
| [Developer guide](DEVELOPER_GUIDE.md) | Developers | Local setup, code map, tests and change workflow |
| [Communication](COMMUNICATION.md) | Controls/integration engineers | OPC UA, MQTT, HTTP and WebSocket contracts |
| [Configuration](CONFIGURATION.md) | Administrators | JSON settings, environment variables and restart behavior |
| [Alarm and event lifecycle](ALARM_AND_EVENT_LIFECYCLE.md) | Operations and developers | Conditions, events, alarms and tasks |
| [Operations runbook](OPERATIONS_RUNBOOK.md) | Service owners | Startup, diagnosis, restart, backup and recovery |
| [Requirements traceability](REQUIREMENTS_TRACEABILITY.md) | Reviewers | Implemented requirement-to-code/test evidence |

Production deployment constraints and owner actions are recorded in
[Production readiness](../PRODUCTION_READINESS.md).

## Scope

The current system simulates one machine (`MACHINE-01`), exposes six PLC tags,
uses either OPC UA or MQTT for MES ingestion, persists to SQL Server, and serves
a FastAPI dashboard. It is a learning and controlled-pilot implementation, not
a high-availability or internet-facing MES.
