FROM python:3.11-slim

ARG INSTALL_OPTIONAL=false

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV WAVEMIND_DB=/data/wavemind.sqlite3
ENV WAVEMIND_LOG_LEVEL=INFO

WORKDIR /app

COPY README.md pyproject.toml requirements.txt requirements-optional.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ "$INSTALL_OPTIONAL" = "true" ]; then pip install --no-cache-dir -r requirements-optional.txt; fi

COPY wavemind ./wavemind
COPY wavemind_v2.py ./wavemind_v2.py
RUN pip install --no-cache-dir -e .

VOLUME ["/data", "/backups"]
EXPOSE 8000

CMD ["uvicorn", "wavemind.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
