# Single container: web app plus the in-process daily refresh (RUN_SCHEDULER=true).
# Dependencies come from uv.lock so the image matches what the tests ran against.
# Playwright + Chromium are required for the CDON adapter.

FROM python:3.13-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
RUN useradd -m -u 1000 tracker

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src/ /app/src/
RUN uv sync --frozen --no-dev --no-editable
ENV PATH="/app/.venv/bin:$PATH" \
    PLAYWRIGHT_BROWSERS_PATH=/app/playwright_browsers

RUN apt-get update && playwright install --with-deps chromium && \
    apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* && \
    mkdir -p /app/data && chown -R tracker:tracker /app

USER tracker

ENV PYTHONUNBUFFERED=1 \
    DB_PATH=/app/data/catalog.db \
    RAW_DIR=/app/data/raw \
    API_HOST=0.0.0.0 \
    API_PORT=8080 \
    RUN_SCHEDULER=true \
    SCHEDULER_INTERVAL_HOURS=24 \
    SCHEDULER_INITIAL_DELAY_SECONDS=300 \
    TZ=Europe/Helsinki

EXPOSE 8080
VOLUME ["/app/data"]

CMD ["python", "-m", "cdon_watcher", "web"]
