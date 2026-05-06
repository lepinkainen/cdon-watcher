# Dockerfile for fly.io deployment
# Single image runs the web service 24/7 plus a daily background task that
# refreshes the catalog (crawl) and checks watchlist prices (monitor).
# Includes Playwright since the daily task needs the listing crawler.

FROM python:3.13-slim AS builder

RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential curl && \
    pip install --no-cache-dir uv && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY src/ /app/src/

RUN uv pip install --system --no-cache -e .

FROM python:3.13-slim AS runtime

COPY --from=builder /usr/local/lib/python3.13/site-packages/ /usr/local/lib/python3.13/site-packages/
COPY --from=builder /usr/local/bin/ /usr/local/bin/

RUN playwright install-deps chromium && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

RUN useradd -m -u 1000 tracker

WORKDIR /app

COPY --chown=tracker:tracker src/ /app/src/

ENV PLAYWRIGHT_BROWSERS_PATH=/app/playwright_browsers
RUN mkdir -p ${PLAYWRIGHT_BROWSERS_PATH} && \
    playwright install chromium && \
    chown -R tracker:tracker ${PLAYWRIGHT_BROWSERS_PATH} /app

USER tracker

RUN mkdir -p /app/data/posters

ENV PYTHONUNBUFFERED=1 \
    DB_PATH=/app/data/cdon_movies.db \
    POSTER_DIR=/app/data/posters \
    CACHE_DB_PATH=/app/data/page_cache.db \
    API_HOST=0.0.0.0 \
    API_PORT=8080 \
    PYTHONPATH=/app

EXPOSE 8080

CMD ["python", "-m", "cdon_watcher", "web"]
