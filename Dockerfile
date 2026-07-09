FROM python:3.11-slim

ARG INSTALL_OPTIONAL=false
ARG INSTALL_OTEL=false
ARG INSTALL_PRODUCTION=false

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV WAVEMIND_DB=/data/wavemind.sqlite3
ENV WAVEMIND_LOG_LEVEL=INFO

WORKDIR /app

RUN if [ "$INSTALL_OPTIONAL" = "true" ] || [ "$INSTALL_PRODUCTION" = "true" ]; then apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*; fi

COPY README.md pyproject.toml requirements.txt requirements-optional.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ "$INSTALL_OPTIONAL" = "true" ]; then pip install --no-cache-dir -r requirements-optional.txt; fi \
    && if [ "$INSTALL_OTEL" = "true" ]; then pip install --no-cache-dir "opentelemetry-api>=1.25" "opentelemetry-sdk>=1.25" "opentelemetry-exporter-otlp>=1.25" "opentelemetry-instrumentation-fastapi>=0.46b0"; fi

COPY wavemind ./wavemind
COPY wavemind_v2.py ./wavemind_v2.py
RUN if [ "$INSTALL_PRODUCTION" = "true" ]; then pip install --no-cache-dir -e ".[production]"; else pip install --no-cache-dir -e .; fi

VOLUME ["/data", "/backups"]
EXPOSE 8000

CMD ["wavemind", "serve", "--host", "0.0.0.0", "--port", "8000"]
