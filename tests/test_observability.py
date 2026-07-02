import builtins

from fastapi.testclient import TestClient

from wavemind import HashingTextEncoder, WaveMind
from wavemind.api import create_app
from wavemind.observability import configure_observability, trace_span


def test_observability_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("WAVEMIND_OTEL_ENABLED", raising=False)

    status = configure_observability()

    assert status.enabled is False
    assert status.reason == "disabled"


def test_observability_reports_missing_optional_dependencies(monkeypatch):
    monkeypatch.setenv("WAVEMIND_OTEL_ENABLED", "1")
    import wavemind.observability as observability

    monkeypatch.setattr(observability, "_CONFIGURED", False)
    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("opentelemetry.sdk"):
            raise ImportError("missing otel sdk")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    status = configure_observability()

    assert status.enabled is False
    assert status.reason == "missing-opentelemetry-dependencies"


def test_trace_span_is_safe_without_configuration():
    with trace_span("test.span", {"ok": True}) as span:
        assert span is None or hasattr(span, "set_attribute")


def test_observability_endpoint_reports_app_status(tmp_path, monkeypatch):
    monkeypatch.delenv("WAVEMIND_OTEL_ENABLED", raising=False)
    mind = WaveMind(
        db_path=tmp_path / "otel.sqlite3",
        width=16,
        height=16,
        layers=1,
        encoder=HashingTextEncoder(vector_dim=16),
    )
    try:
        with TestClient(create_app(mind=mind)) as client:
            response = client.get("/observability")

        assert response.status_code == 200
        assert response.json()["enabled"] is False
        assert response.json()["fastapi_instrumented"] is False
    finally:
        mind.close()


def test_metrics_endpoint_reports_api_operation_latency_and_failures(tmp_path, monkeypatch):
    monkeypatch.delenv("WAVEMIND_OTEL_ENABLED", raising=False)
    mind = WaveMind(
        db_path=tmp_path / "api-metrics.sqlite3",
        width=16,
        height=16,
        layers=1,
        encoder=HashingTextEncoder(vector_dim=16),
    )
    try:
        with TestClient(create_app(mind=mind), raise_server_exceptions=False) as client:
            remember = client.post(
                "/remember",
                json={"text": "Andrey tests observability metrics", "namespace": "obs"},
            )
            assert remember.status_code == 200

            query = client.post(
                "/query",
                json={"query": "observability metrics", "namespace": "obs", "top_k": 1},
            )
            assert query.status_code == 200

            def fail_save(*args, **kwargs):
                raise RuntimeError("backup destination unavailable")

            monkeypatch.setattr(mind, "save", fail_save)
            failed_backup = client.post("/backup", json={"path": str(tmp_path / "backup.sqlite3")})
            assert failed_backup.status_code == 500

            metrics = client.get("/metrics").text

        assert "wavemind_api_remember_requests_total 1" in metrics
        assert "wavemind_api_query_requests_total 1" in metrics
        assert "wavemind_api_query_avg_latency_ms " in metrics
        assert "wavemind_api_query_p95_latency_ms " in metrics
        assert "wavemind_api_backup_requests_total 1" in metrics
        assert "wavemind_api_backup_failures_total 1" in metrics
    finally:
        mind.close()
