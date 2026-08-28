# Configuration

## JSON settings

`config/settings.json` is loaded and saved by `mes.config`.

| Key | Meaning and validation |
| --- | --- |
| `pressure.warning`, `pressure.critical` | Non-negative warning and positive critical; warning must be lower |
| `temperature.warning`, `temperature.critical` | Same validation; warning is also the recovery threshold |
| `simulation_update_interval` | Seconds, greater than 0 and at most 60 |
| `production_interval_ticks` | Integer from 1 through 3600 |
| `opc_endpoint` | 12–300 characters beginning `opc.tcp://` |
| `communication_mode` | `OPC_UA` or `MQTT` |
| `mqtt_broker_host` / `mqtt_broker_port` | Broker address; port 1–65535 |
| `mqtt_topic_prefix` | Non-empty prefix, maximum 200 characters |

Security sections configure dashboard authentication/session/audit, OPC UA
mode/policy/certificate paths, and MQTT TLS/username/certificate paths. Enabling
secured OPC UA requires client and server certificates and keys. MQTT TLS
requires a CA and username; client certificate and key must be supplied together.

## Environment variables

| Variable | Use |
| --- | --- |
| `MES_SQL_PASSWORD` | SQL Server `sa` secret used by Compose |
| `MES_SQL_CONNECTION` | Repository connection string; Compose supplies its own container address |
| `MES_DASHBOARD_SECRET` | Session HMAC key; at least 32 characters when auth is enabled |
| `MES_ADMIN_USERNAME`, `MES_ADMIN_PASSWORD` | Admin account |
| `MES_OPERATOR_USERNAME`, `MES_OPERATOR_PASSWORD` | Operator account |
| `MES_COOKIE_SECURE` | Truthy value adds the Secure session-cookie flag; use with HTTPS |
| `MES_MQTT_PASSWORD` | MQTT credential; never stored in JSON |
| `MES_BIND_ADDRESS` | Host bind address for published Compose ports; default `127.0.0.1` |
| `MES_MQTT_HOST`, `MES_MQTT_PORT` | Runtime broker override used by the controller |
| `MES_DASHBOARD_HOST`, `MES_DASHBOARD_PORT` | Uvicorn listen address and port |
| `MES_LOG_LEVEL` | Root application log level; default `INFO` |
| `MES_CONTAINERIZED` | Enables container restart behavior and runtime diagnostics |

## Restart behavior

Thresholds and simulation/order timing update in the current process. Changing
OPC endpoint, communication mode, MQTT address or topic reports restart required
from configuration save. Security save always reports restart required. The UI
shows “Not saved” only after an editable security value changes and offers the
admin restart after a successful change that requires it.

Paths in the checked-in container configuration are relative to `/app` and must
match the mounted `certs` and `config` directories.
