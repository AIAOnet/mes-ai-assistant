# Production-readiness review

Reviewed: 2026-08-29

## Decision

**Ready for a controlled single-host pilot**, after the deployment owner completes
the environment-specific actions below. The application has automated regression,
health, monitoring, backup, and recovery coverage. It is not yet designed as a
high-availability or internet-facing service.

## Verified controls

- Dashboard authentication uses signed, expiring, HTTP-only, strict SameSite cookies.
- Administrators and operators have separate authorization scopes and audited writes.
- OPC UA uses SignAndEncrypt and MQTT uses TLS, client certificates, and credentials.
- Runtime secrets, private certificates, broker passwords, and backups are ignored by Git.
- SQL Server, MQTT, and the dashboard have container health checks and bounded logs.
- JSON request logs contain correlation IDs and redact sensitive values.
- Prometheus metrics, dependency alerts, diagnostics, and recent errors are available.
- Database backups use checksums, integrity verification, retention, and SHA-256 hashes.
- A full backup was restored into and removed from a disposable recovery database.
- Published host ports default to loopback rather than every network interface.
- Browser responses include CSP, anti-framing, no-sniff, and referrer-policy headers.

## Deployment-owner actions

- Terminate HTTPS at a trusted reverse proxy and set `MES_COOKIE_SECURE=true`.
- Replace all learning credentials and store them in the platform secret manager.
- Restrict `/metrics` to the trusted monitoring network at the proxy/firewall.
- Pin and approve the SQL Server and Python base-image digests in the deployment system.
- Store encrypted database and configuration backups on a separate failure domain.
- Define recovery objectives, certificate rotation ownership, alert routing, and on-call coverage.
- Run vulnerability and license scanning in CI for Python packages and container images.

## Accepted limitations

- The deployment is a single host with no automatic failover or horizontal scaling.
- Metrics and recent errors are in memory and reset when the dashboard restarts.
- Development certificates are suitable for the learning environment only.
- SQL Server Developer edition is not licensed for production workloads.
- The local Compose file exposes services only on loopback by default; remote access
  requires an explicitly secured bind address and firewall policy.

Run `./scripts/production-readiness.ps1` after every deployment. A release is
eligible only when it ends with `READY` and the regression and recovery drills pass.
