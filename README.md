# Movie offers

Single-user tracker of physical movie offers (Blu-ray, 4K UHD) at Levykauppa Äx
and CDON. A daily refresh archives the store listings, parses them offline,
imports price observations into SQLite, and matches titles against TMDB. The
web UI shows watched movies in stock first, then every in-stock offer under
Blu-ray ≤ €10 / 4K ≤ €20, with one-click ignore and watch.

Spec and decisions: `docs/09_multi_store_plan.md`. Debugging a broken store:
`ai-docs/crawler-investigation.md`.

## Run locally

```bash
task install                                   # uv deps + Playwright Chromium
cp .env.example .env                           # set TMDB_API_KEY
uv run python -m cdon_watcher refresh          # first crawl of both stores
uv run python -m cdon_watcher web              # http://localhost:8080
```

## Run in Docker

```bash
docker compose build
TMDB_API_KEY=... docker compose up -d          # web on :8080, refresh daily in-process
```

Data (SQLite, raw page archive) lives in `./data`, mounted into the container.
To schedule from host cron instead, set `RUN_SCHEDULER=false` and run
`docker compose exec app python -m cdon_watcher refresh`.

## Develop

```bash
task test        # unit tests, no network
task test-live   # live store shape tests
task build       # tests + lint; run before every commit
```
