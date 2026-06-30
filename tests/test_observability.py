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
