# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## Essential Commands

```bash
task install                 # uv sync + Playwright Chromium (one-time)
task build                   # ALWAYS run before finishing: unit tests + lint
task test                    # Fast unit tests, no network
task test-live               # Live store shape tests (network; Chromium for CDON)
task lint-fix                # ruff + prettier auto-fix

uv run python -m cdon_watcher web                      # Web app at :8080
uv run python -m cdon_watcher refresh [--store ax|cdon] # crawl → parse → import → match
uv run python -m cdon_watcher crawl-raw --store ax     # Stage 1 only: archive listing pages
uv run python -m cdon_watcher parse-raw --store ax     # Stage 2 only: parsed.json from latest run
uv run python -m cdon_watcher import-run --store ax    # Stage 3 only: import parsed.json
uv run python -m cdon_watcher match                    # Stage 4 only: TMDB matching

# Run one test
PYTHONPATH=./src uv run pytest tests/unit/test_file.py -k "test_name"
```

## What this is

Single-user tracker of physical movie offers (Blu-ray, 4K UHD) at two stores:
Levykauppa Äx (`/leffat/offer/`) and CDON (`/elokuvat/`). Daily refresh,
read-mostly web UI, SQLite. No auth; runs locally or on a VPS behind Tailscale,
in one Docker container. Spec: `docs/09_multi_store_plan.md`.

## Architecture

```
crawl-raw            parse-raw              import-run            match
┌──────────────┐    ┌────────────────┐    ┌────────────────┐    ┌──────────────┐
│ StoreAdapter │───▶│ Store parser   │───▶│ catalog.importer│──▶│ catalog.     │
│ + fetcher    │    │ (offline, from │    │ idempotent,    │    │ matching     │
│ data/raw/    │    │ saved bodies)  │    │ store-scoped   │    │ TMDB, 1 req/ │
│ <store>/<run>│    │ → parsed.json  │    │ observations   │    │ product      │
└──────────────┘    └────────────────┘    └────────────────┘    └──────────────┘
                                                   │
                                          ┌────────▼────────┐
                                          │ web/catalog_routes + catalog.queries │
                                          │ "/" watchlist first, then offers under│
                                          │ caps (BD ≤ €10, 4K ≤ €20)             │
                                          └─────────────────┘
```

| Layer     | Files                                                                                                                                                                         |
| --------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Ingestion | `ingestion/stores.py` (adapters), `crawler.py`, `browser.py` (Playwright for CDON), `archive.py`, `ax_parser.py`, `cdon_parser.py`, `parse.py`, `contract.py`, `normalize.py` |
| Catalog   | `catalog/models.py`, `db.py` (versioned migrations), `importer.py`, `matching.py`, `tmdb.py`, `preferences.py`, `queries.py`                                                  |
| Web       | `web/app.py`, `web/catalog_routes.py`, `web/filters.py`, `templates/`, `static/`                                                                                              |
| Ops       | `refresh.py` (stage orchestration + per-store lock), `scheduler.py` (in-process daily), `cli.py`, `config.py`                                                                 |

Store facts that drive the design:

- Äx: plain HTTP, listing rows carry everything (price, `<del>` regular price, stock text, format, edition id in URL fragment). Offer category membership defines scope; a complete run expires unseen products.
- CDON: Cloudflare challenge blocks plain HTTP, so `BrowserFetcher` renders listings in headless Chromium. Products come from `__NEXT_DATA__` articles (price, stock count, condition, `preset_media_format`). First N pages only; no product pages; no membership expiry, freshness (48 h) hides stale rows.
- Collections (multi-movie boxes, TV seasons) are shown as-is under the store title and never matched.

## Pages and endpoints

- `/` main page: watchlist-in-stock section first, then in-stock offers under the hardcoded caps. Query params `max_bd`, `max_4k` (euros), `format=bd|4k`, `store=ax|cdon`, `condition=new|used`, `q`.
- `/watchlist`, `/queue` (manual TMDB matching), `/ignored`, `/products/<id>` (price history), `/status`.
- `POST /api/v2/products/<id>/{watch|unwatch|ignore|unignore}`; `POST /api/v2/products/<id>/match` with `{"tmdb_id": int|null}`; `GET /api/v2/tmdb/search?q=`.

## Project Patterns

- **Package manager**: `uv` only (`uv run`, `uv sync`).
- **Types**: strict mypy on `src`; ruff with 100-char lines and C901 complexity 10.
- **Database**: sync SQLModel over SQLite. `CatalogModel` has its own metadata. Schema changes go through `catalog/db.py::MIGRATIONS` with a new version number; never silence schema errors.
- **Money**: integer cents everywhere; `euros` Jinja filter for display.
- **Timestamps**: naive UTC in the database (`importer.utc_naive`).
- **Templates**: Jinja; excluded from prettier (it splits `{% %}` tags).
- **Fixtures**: gzip page captures under `tests/fixtures/<store>/` with a README per store. Unit tests never touch the network; `tests/integration/test_live_stores.py` does.
- **Politeness**: one listing fetch per page, 2 s delay, a browser-identifying User-Agent for CDON only because the site requires a browser.

## Environment Variables

See `.env.example`. Key ones: `TMDB_API_KEY` (matching skipped without it),
`DB_PATH` (`./data/catalog.db`), `RAW_DIR`, `STORES`, `MAX_PAGES_PER_CATEGORY`,
`RUN_SCHEDULER` (in-process daily refresh; leave off when host cron runs
`refresh`), `SCHEDULER_INTERVAL_HOURS`.

## LLM Guidelines

Shared conventions come from the `llm-shared` MCP server (no longer a
submodule). Key rules it carries:

- Python: uv, ruff, strict mypy
- Shell: use `rg` instead of `grep`, `fd` instead of `find`
- GitHub: never commit to main directly, use feature branches

When a store breaks, follow `ai-docs/crawler-investigation.md`.
