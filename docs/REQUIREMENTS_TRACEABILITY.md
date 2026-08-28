# Requirements traceability

This matrix maps the phased MES specification in the root [README](../README.md)
to current implementation and automated evidence.

| Requirement | Implementation evidence | Test/operation evidence | Status |
| --- | --- | --- | --- |
| Simulate one machine and PLC tags | `machine/simulator.py`, `machine/plc.py` | `tests/test_machine.py` | Implemented |
| OPC UA subscribed data path | `opc/server.py`, `mes/opc_client.py` | `tests/test_opc.py` | Implemented |
| Stateful threshold events | `mes/rules.py`, `mes/events.py`, `mes/processor.py` | `tests/test_mes.py` | Implemented |
| Alarm acknowledgement and recovery | `mes/alarms.py` | `tests/test_mes.py` | Implemented |
| Alarm-created maintenance work | `mes/tasks.py` | `tests/test_mes.py` | Implemented |
| SQL persistence and audit | `database/schema.sql`, `database/repository.py` | bootstrap plus controller integration tests | Implemented |
| Unified web dashboard | `dashboard/api.py`, `dashboard/index.html`, `dashboard/app.js` | live readiness and regression checks | Implemented |
| Production orders and OEE | `mes/production.py`, controller/API/UI | `tests/test_production.py` | Implemented |
| Selectable OPC UA/MQTT | controller plus `mes/mqtt_client.py` | controller and MQTT security tests | Implemented |
| Educational data-flow trace | `mes/processor.py`, dashboard Data Flow UI, `lineage/` | `test_trace_explains_transport_rule_and_alarm_lineage` | Implemented |
| Dashboard auth and two roles | `dashboard/auth.py`, API middleware | `tests/test_auth.py`, readiness/live role checks | Implemented |
| OPC UA and MQTT transport security | OPC/MQTT adapters and certificate generators | controller validation, OPC and MQTT tests | Implemented for local pilot |
| Reliable container startup | `Dockerfile`, `docker-compose.yml` | Compose health and readiness audit | Implemented |
| Structured logging and diagnostics | logging config, middleware, Diagnostics UI | logging tests and live correlation checks | Implemented |
| Metrics and operational alerts | `dashboard/monitoring.py`, `/metrics` | `tests/test_monitoring.py` | Implemented in memory |
| Backup and disaster recovery | `scripts/backup-database.ps1`, restore/recovery scripts | disposable recovery drill | Implemented |
| Production-readiness gate | readiness script and report | all checks produce `READY` | Implemented for controlled pilot |

## Known gaps requiring site requirements

- No defined RTO, RPO, retention approval, off-host backup target or restore owner.
- No site identity provider, password rotation policy or named account owners.
- No production CA/trust enrollment or certificate rotation/expiry policy.
- No alert receiver, severity SLA, escalation contacts or on-call schedule.
- No high availability, automatic failover, horizontal scaling or runtime-state
  rehydration requirement has been implemented.
- No approved production license/image digest, vulnerability threshold or SBOM
  policy is specified.
- No plant-specific tag namespace, units, sampling rate, equipment hierarchy,
  network zones or firewall rules are supplied.

These are intentionally recorded as gaps rather than inferred requirements.
