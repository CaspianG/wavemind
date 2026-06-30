from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator


logger = logging.getLogger("wavemind.observability")
_CONFIGURED = False


@dataclass(frozen=True)
class ObservabilityStatus:
    enabled: bool
    exporter: str
    service_name: str
    reason: str | None = None

    def as_dict(self) -> dict[str, str | bool | None]:
        return {
            "enabled": self.enabled,
            "exporter": self.exporter,
            "service_name": self.service_name,
            "reason": self.reason,
        }


def _env_enabled(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).lower() in {"1", "true", "yes", "on"}


def configure_observability(
    service_name: str | None = None,
    service_version: str | None = None,
) -> ObservabilityStatus:
    """Configure OpenTelemetry when explicitly enabled by environment.

    WaveMind keeps OpenTelemetry optional: production deployments can enable it
    with `WAVEMIND_OTEL_ENABLED=1`, while local installs do not need any OTEL
    packages.
    """

    global _CONFIGURED
    service_name = service_name or os.environ.get("WAVEMIND_OTEL_SERVICE_NAME", "wavemind")
    exporter_name = os.environ.get("WAVEMIND_OTEL_EXPORTER", "otlp").lower()

    if not _env_enabled("WAVEMIND_OTEL_ENABLED"):
        return ObservabilityStatus(
            enabled=False,
            exporter=exporter_name,
            service_name=service_name,
            reason="disabled",
        )
    if _CONFIGURED:
        return ObservabilityStatus(
            enabled=True,
            exporter=exporter_name,
            service_name=service_name,
        )

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:
        logger.warning("OpenTelemetry is enabled but dependencies are missing: %s", exc)
        return ObservabilityStatus(
            enabled=False,
            exporter=exporter_name,
            service_name=service_name,
            reason="missing-opentelemetry-dependencies",
        )

    resource_attrs: dict[str, str] = {"service.name": service_name}
    if service_version:
        resource_attrs["service.version"] = service_version
    provider = TracerProvider(resource=Resource.create(resource_attrs))

    try:
        if exporter_name == "console":
            from opentelemetry.sdk.trace.export import ConsoleSpanExporter

            exporter = ConsoleSpanExporter()
        else:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            endpoint = os.environ.get("WAVEMIND_OTEL_ENDPOINT")
            exporter = OTLPSpanExporter(endpoint=endpoint) if endpoint else OTLPSpanExporter()
    except ImportError as exc:
        logger.warning("OpenTelemetry exporter is missing: %s", exc)
        return ObservabilityStatus(
            enabled=False,
            exporter=exporter_name,
            service_name=service_name,
            reason="missing-opentelemetry-exporter",
        )

    provider.add_span_processor(BatchSpanProcessor(exporter))
    try:
        trace.set_tracer_provider(provider)
    except Exception as exc:  # pragma: no cover - depends on global OTEL state.
        logger.debug("OpenTelemetry tracer provider was already set: %s", exc)
    _CONFIGURED = True
    return ObservabilityStatus(
        enabled=True,
        exporter=exporter_name,
        service_name=service_name,
    )


def instrument_fastapi_app(app: Any) -> bool:
    if not _env_enabled("WAVEMIND_OTEL_ENABLED"):
        return False
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    except ImportError:
        logger.warning("OpenTelemetry FastAPI instrumentation is not installed")
        return False
    FastAPIInstrumentor.instrument_app(app)
    return True


@contextmanager
def trace_span(name: str, attributes: dict[str, Any] | None = None) -> Iterator[Any]:
    try:
        from opentelemetry import trace
    except ImportError:
        yield None
        return

    tracer = trace.get_tracer("wavemind")
    with tracer.start_as_current_span(name) as span:
        if span is not None and attributes:
            for key, value in attributes.items():
                if value is None:
                    continue
                if isinstance(value, (str, bool, int, float)):
                    span.set_attribute(key, value)
                elif isinstance(value, (list, tuple)):
                    span.set_attribute(
                        key,
                        [item for item in value if isinstance(item, (str, bool, int, float))],
                    )
        yield span
