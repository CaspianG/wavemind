from pathlib import Path


def test_observability_docs_link_real_metrics_and_local_configs():
    guide = Path("docs/OBSERVABILITY.md").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")
    prometheus = Path("examples/observability/prometheus.yml").read_text(encoding="utf-8")
    alerts = Path("examples/observability/prometheus-alerts.yml").read_text(encoding="utf-8")
    collector = Path("examples/observability/otel-collector.yaml").read_text(encoding="utf-8")
    compose = Path("examples/observability/docker-compose.yml").read_text(encoding="utf-8")

    assert "docs/OBSERVABILITY.md" in readme
    assert "docker compose -f examples/observability/docker-compose.yml up --build" in guide
    assert "wavemind_api_query_p95_latency_ms" in guide
    assert "wavemind_api_backup_failures_total" in guide
    assert "wavemind_api_index_rebuild_failures_total" in guide
    assert "wavemind_index_healthy" in guide

    assert "targets: [\"wavemind:8000\"]" in prometheus
    assert "prometheus-alerts.yml" in prometheus
    assert "WaveMindHighQueryLatency" in alerts
    assert "wavemind_api_query_p95_latency_ms > 1000" in alerts
    assert "increase(wavemind_api_backup_failures_total[10m]) > 0" in alerts
    assert "increase(wavemind_api_index_rebuild_failures_total[10m]) > 0" in alerts
    assert "wavemind_index_healthy == 0" in alerts

    assert "endpoint: 0.0.0.0:4318" in collector
    assert "exporters:" in collector
    assert 'INSTALL_OTEL: "true"' in compose
    assert "WAVEMIND_OTEL_ENDPOINT: http://otel-collector:4318/v1/traces" in compose
