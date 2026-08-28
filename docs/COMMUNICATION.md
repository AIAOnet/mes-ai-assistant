# Communication

## PLC tag contract

| Tag | Type | Source |
| --- | --- | --- |
| `Machine01.Pressure` | float | Machine pressure |
| `Machine01.Temperature` | float | Machine temperature |
| `Machine01.RPM` | integer | Machine speed |
| `Machine01.Status` | string | `RUNNING` or `STOPPED` |
| `Machine01.ProductionCount` | integer | Produced-unit counter |
| `Machine01.AlarmState` | boolean | Always false; MES rules determine alarms |

## OPC UA

`OPCUAServer` exposes the PLC tags below the configured endpoint. `MESOPCClient`
subscribes to the nodes and forwards data-change callbacks to the event
processor. Supported security modes are `None`, `Sign`, and `SignAndEncrypt`;
supported policies are `None`, `Basic256Sha256`, and
`Aes128_Sha256_RsaOaep`. Secured mode requires client and server certificate/key
paths. The checked-in configuration uses `SignAndEncrypt` with
`Basic256Sha256`.

## MQTT

The dashboard transport publishes values changed since the preceding scan under
the configured topic prefix and subscribes to the same prefix. The implementation uses the broker host,
port, prefix, TLS CA, optional client certificate/key, username and the
`MES_MQTT_PASSWORD` environment secret. Mosquitto listens on 8883, disables
anonymous access, requires a client certificate and TLS 1.2, and also checks its
password file.

## Dashboard protocols

- HTTP serves the UI and REST operations.
- `/ws/live` sends a complete controller snapshot every 0.5 seconds. When
  dashboard authentication is enabled, a valid session cookie is required or
  the socket closes with code 4401.
- `/healthz` is an unauthenticated readiness endpoint.
- `/metrics` is an unauthenticated Prometheus text endpoint and should be
  restricted by the deployment proxy/firewall.
- API responses include an `X-Request-ID`; callers may supply one (truncated to
  100 characters). Requests are logged with that correlation ID.

## Transport switching

`POST /api/communication/mode` accepts only `OPC_UA` or `MQTT`. Switching stops
the current MES transport, starts the requested transport, changes
`communication_mode`, and saves `config/settings.json`. A connection failure is
reported as HTTP 503.
