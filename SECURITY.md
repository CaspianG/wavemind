# Security Policy

WaveMind is early-stage software. Do not expose a public WaveMind API without
enabling authentication, rate limiting, TLS termination, backups, and access
logs.

## Supported Versions

Only the latest release on `main` is actively maintained today.

## Reporting A Vulnerability

Please open a private security advisory on GitHub if available for the
repository. If not available, open a minimal public issue that describes the
affected surface without exploit details, and ask for a private contact path.

Useful details:

- WaveMind version;
- API deployment mode;
- whether `WAVEMIND_API_KEYS` / role keys are enabled;
- whether the database is local SQLite, pgvector, or another backend;
- reproduction steps;
- impact and suggested mitigation.

## Production Baseline

For production deployments:

- set API keys with `WAVEMIND_READ_KEYS`, `WAVEMIND_WRITE_KEYS`, and
  `WAVEMIND_ADMIN_KEYS` or `WAVEMIND_API_KEYS`;
- set `WAVEMIND_RATE_LIMIT_PER_MINUTE`;
- keep SQLite files and backups outside committed repositories;
- use TLS at the reverse proxy or ingress;
- monitor `/metrics`;
- review `/audit` events;
- use namespaces for tenant isolation;
- run regular backups and restore tests.
