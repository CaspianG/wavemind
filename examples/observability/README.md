# WaveMind Observability Example

This folder contains a free local observability stack:

- `docker-compose.yml` - WaveMind API, OpenTelemetry Collector, and Prometheus.
- `otel-collector.yaml` - accepts OTLP traces and logs them through the debug exporter.
- `prometheus.yml` - scrapes WaveMind `/metrics`.
- `prometheus-alerts.yml` - example alert rules for latency, backup failures,
  index rebuild failures, and index health.

Run from the repository root:

```sh
docker compose -f examples/observability/docker-compose.yml up --build
```

See [`docs/OBSERVABILITY.md`](../../docs/OBSERVABILITY.md) for the full guide.

