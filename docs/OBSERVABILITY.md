# WaveMind Observability

WaveMind exposes two observability paths:

- Prometheus-compatible metrics at `GET /metrics`;
- optional OpenTelemetry traces for API and core memory operations.

Both are local-first. They do not require a hosted monitoring vendor.

## Quick Local Stack

Run WaveMind, an OpenTelemetry Collector, and Prometheus from the repository
root:

```sh
docker compose -f examples/observability/docker-compose.yml up --build
```

Then open:

- WaveMind API: <http://127.0.0.1:8000/stats>
- WaveMind Studio: <http://127.0.0.1:8000/studio>
- Prometheus: <http://127.0.0.1:9090>

Generate a few metrics:

```sh
curl -X POST http://127.0.0.1:8000/remember \
  -H "Content-Type: application/json" \
  -d '{"text":"Andrey is testing WaveMind observability","namespace":"demo"}'

curl -X POST http://127.0.0.1:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query":"observability","namespace":"demo","top_k":1}'

curl http://127.0.0.1:8000/metrics
```

## Prometheus Metrics

`GET /metrics` returns Prometheus text format.

Core state gauges:

- `wavemind_active_memories`
- `wavemind_expired_memories`
- `wavemind_total_memories`
- `wavemind_audit_events`
- `wavemind_field_energy`
- `wavemind_graph_nodes`
- `wavemind_graph_edges`
- `wavemind_index_healthy`
- `wavemind_index_expected_records`
- `wavemind_index_vector_records`
- `wavemind_index_missing_records`
- `wavemind_index_extra_records`

API operation counters and recent in-process latency gauges:

- `wavemind_api_remember_requests_total`
- `wavemind_api_query_requests_total`
- `wavemind_api_query_failures_total`
- `wavemind_api_query_avg_latency_ms`
- `wavemind_api_query_p95_latency_ms`
- `wavemind_api_backup_failures_total`
- `wavemind_api_index_rebuild_failures_total`

The latency gauges are based on recent in-process samples. They are useful for
small deployments and local demos. For production percentile history, scrape
them into Prometheus or use OpenTelemetry traces.

## Prometheus Alerts

Example alert rules are in:

```text
examples/observability/prometheus-alerts.yml
```

Included alerts:

- `WaveMindHighQueryLatency` - query p95 latency is above 1000 ms.
- `WaveMindBackupFailures` - at least one backup operation failed recently.
- `WaveMindIndexRebuildFailures` - at least one index rebuild failed recently.
- `WaveMindIndexUnhealthy` - source-of-truth memory count and vector index count
  drifted.

The local Prometheus config loads these rules from:

```text
examples/observability/prometheus.yml
```

Useful Prometheus queries:

```promql
wavemind_api_query_p95_latency_ms
rate(wavemind_api_query_requests_total[5m])
increase(wavemind_api_backup_failures_total[10m])
wavemind_index_healthy
wavemind_index_missing_records
```

## OpenTelemetry Traces

OpenTelemetry is optional and off by default.

Install the optional dependencies:

```sh
python -m pip install "wavemind[otel]"
```

Enable OTLP/HTTP traces:

```sh
export WAVEMIND_OTEL_ENABLED=1
export WAVEMIND_OTEL_SERVICE_NAME=wavemind-local
export WAVEMIND_OTEL_EXPORTER=otlp
export WAVEMIND_OTEL_ENDPOINT=http://127.0.0.1:4318/v1/traces
wavemind serve
```

For Windows PowerShell:

```powershell
$env:WAVEMIND_OTEL_ENABLED = "1"
$env:WAVEMIND_OTEL_SERVICE_NAME = "wavemind-local"
$env:WAVEMIND_OTEL_EXPORTER = "otlp"
$env:WAVEMIND_OTEL_ENDPOINT = "http://127.0.0.1:4318/v1/traces"
wavemind serve
```

For local debugging without a collector:

```sh
export WAVEMIND_OTEL_ENABLED=1
export WAVEMIND_OTEL_EXPORTER=console
wavemind serve
```

WaveMind creates spans for:

- `wavemind.remember.encode`
- `wavemind.remember.store`
- `wavemind.remember.index`
- `wavemind.remember.field`
- `wavemind.query.encode`
- `wavemind.query.index_search`
- `wavemind.query.graph`
- `wavemind.query.rerank`
- `wavemind.forget.store`
- `wavemind.forget.index`
- `wavemind.save`
- `wavemind.load`
- `wavemind.index.rebuild`

FastAPI request instrumentation is enabled when
`opentelemetry-instrumentation-fastapi` is installed and
`WAVEMIND_OTEL_ENABLED=1`.

Check runtime status:

```sh
curl http://127.0.0.1:8000/observability
```

## Minimal Dashboard Panels

For a Prometheus or Grafana dashboard, start with:

| Panel | Query |
|---|---|
| Query p95 latency | `wavemind_api_query_p95_latency_ms` |
| Query throughput | `rate(wavemind_api_query_requests_total[5m])` |
| Query failures | `increase(wavemind_api_query_failures_total[10m])` |
| Memory count | `wavemind_active_memories` |
| Index health | `wavemind_index_healthy` |
| Index drift | `wavemind_index_missing_records + wavemind_index_extra_records` |
| Backup failures | `increase(wavemind_api_backup_failures_total[10m])` |
| Rebuild failures | `increase(wavemind_api_index_rebuild_failures_total[10m])` |

Traces should be used to inspect where latency is spent: encoding, candidate
index search, graph expansion, reranking, storage, or backup.

## Production Notes

- Keep `/metrics` behind the same network controls as the API.
- If API keys are enabled, configure the scraper or reverse proxy to pass a
  read-capable key.
- OpenTelemetry traces may include namespaces, top-k values, and operation
  metadata. Do not attach raw user text to spans.
- For multi-process deployments, scrape each process separately or put metrics
  behind a gateway that preserves instance labels.
- The built-in latency gauges are process-local. For long retention and alert
  history, store metrics in Prometheus or another time-series backend.

