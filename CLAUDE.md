# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Essential Commands

```bash
task install                 # uv sync + Playwright Chromium (one-time)
task build                   # ALWAYS run before finishing: unit tests + lint
task test                    # Fast unit tests, no network
task test-live               # Live store shape tests (network; Chromium for CDON)
task lint                    # ruff check + ruff format --check + mypy src + npx prettier --check
task lint-fix                # ruff + prettier auto-fix

uv run python -m shelfwatch web                      # Web app at :8080
uv run python -m shelfwatch refresh [--store ax|cdon|mymovies] # crawl → parse → import → match (-v: per-page progress)
uv run python -m shelfwatch refresh --search-only   # sync + wishlist searches only, no category crawl
uv run python -m shelfwatch crawl-raw --store ax     # Stage 1 only: archive listing pages
uv run python -m shelfwatch parse-raw --store ax     # Stage 2 only: parsed.json from latest run
uv run python -m shelfwatch import-run --store ax    # Stage 3 only: import parsed.json
uv run python -m shelfwatch match                    # Stage 4 only: TMDB matching
uv run python -m shelfwatch sync                     # Pull owned + wanted from moviecatalog
uv run python -m shelfwatch search --store cdon      # Wishlist searches only (+ import, match)

# Run one test
PYTHONPATH=./src uv run pytest tests/unit/test_file.py -k "test_name"
```

`test_ui_integration.py` in the repo root is a manual, headed-browser script
against a running server, not part of the pytest suite (`testpaths = ["tests"]`).

## What this is

Single-user tracker of physical movie offers (Blu-ray, 4K UHD) at three stores:
Levykauppa Äx (`/leffat/offer/`), CDON (`/elokuvat/`) and MyMovies (in-stock
catalogue). Daily refresh,
read-mostly web UI, SQLite. No auth; runs locally or on a VPS behind Tailscale,
in one Docker container. Spec: `docs/09_multi_store_plan.md` (phase 2 is the
moviecatalog integration).

Paired with **moviecatalog** (`../moviecatalog`, Go), which owns what I own and
want. The watcher keeps no state about me except ignores. Contract in both
directions: moviecatalog's `SPEC.md`, "Connecting to the watcher". Change it
there first; its `internal/offers` decodes `/api/v2/offers`.

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
                                          │ "/" offers under caps (BD ≤ €15,      │
                                          │ 4K ≤ €20); "/in-stock" wishlist       │
                                          └─────────────────┘
```

| Layer     | Files                                                                                                                                                                                                                                                                           |
| --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Ingestion | `ingestion/stores.py` (adapters), `mymovies.py` (MyMovies fetcher, adapter), `crawler.py`, `browser.py` (Playwright for CDON), `archive.py`, `ax_parser.py`, `cdon_parser.py`, `mymovies_parser.py`, `parse.py`, `contract.py`, `normalize.py`, `search.py` (wishlist searches) |
| Catalog   | `catalog/models.py`, `db.py` (versioned migrations), `importer.py`, `matching.py`, `tmdb.py`, `preferences.py`, `queries.py`, `catalogue.py` (moviecatalog)                                                                                                                     |
| Web       | `web/app.py`, `web/catalog_routes.py`, `web/filters.py`, `templates/`, `static/`                                                                                                                                                                                                |
| Ops       | `refresh.py` (stage orchestration + per-store lock), `scheduler.py` (in-process daily), `cli.py`, `config.py`                                                                                                                                                                   |

Refresh order: `sync` (GET moviecatalog `/api/sync`, stored in `catalogue_sync`;
failure keeps the stored lists) → per store: category crawl/parse/import →
wishlist searches (`ingestion/search.py`, archive scope `wish-search`) →
parse/import → match. Search runs share the store lock, delay and browser.

Matching with `JEV_API_KEY`: the box-set gate runs before matching. When the
title scores can't decide, `catalog/jev.py` asks Jev to pick among the top 5
TMDB candidates (with popularity, vote count and Finnish titles from
`movie_titles`). Accept, review (`ambiguous`) or none (`unmatched`) follows
`jev.decide`. All question wording and thresholds live in `catalog/jev.py`.
`match --retry-ambiguous` sends existing ambiguous matches back through it.
Unit tests blank `JEV_API_KEY` (`tests/conftest.py`).

Discovery source: `store_products.category_member` (seen by the newest category
crawl) and `search_hits` (found by the latest search for a wished movie). A
product stays active while either holds. Matching checks search hits against
the wished movie first (`score_target`), then falls back to open TMDB search.

Store facts that drive the design:

- Äx: plain HTTP, listing rows carry everything (price, `<del>` regular price, stock text, format, edition id in URL fragment). The crawl makes four passes over the offer category, one per format filter (`?f2=blu|uhd|ultrasb|blusb`), sorted cheapest first (`o2=p`), each capped at `MAX_PAGES_PER_CATEGORY` pages: storewide sales put tens of thousands of products "on offer". A complete run expires unseen products, including offers priced past the cap.
- CDON: Cloudflare challenge blocks plain HTTP, so `BrowserFetcher` renders listings in headless Chromium. Products come from `__NEXT_DATA__` articles (price, stock count, condition, `preset_media_format`). First N pages only; no product pages; no membership expiry, freshness (48 h) hides stale rows.
- MyMovies: `/tuotteet.php` is an empty shell; its script POSTs the filter form to `/ajax/hae-tuotteet2.php`, which returns JSON with result cards as HTML. `MyMoviesFetcher` turns an archived `/tuotteet.php?q=&saatavuus=&page=` URL into that POST (fixed filters: Blu-ray + 4K only, new + used, all types, title search). The crawl is the empty query with `saatavuus=1` (all in-stock products, 60 per page, about 50 pages); a complete run expires unseen products. Searches send `saatavuus=0`. Each card has a new and a used price with separate stock (buy button `data-uusi` / `data-kaytetty`), so one card becomes products `<id>:new` and `<id>:used`. No product pages. Requests need a desktop Chrome User-Agent (403 otherwise). Details: `docs/11_mymovies.md`.
- Box sets (`is_collection`: several different films, TV seasons) are never matched and live on `/box-sets`, not `/`. Title patterns (`box_set_detector.py`) flag them at parse time; the Jev gate (`gate_box_sets`) asks once per title for the rest and stores `box_set_probability` (re-asked when the raw title changes). Over 0.7 is a box set; 0.3–0.7 is matched as usual but never accepted automatically (lands in `/queue`); a failed Jev call leaves the product unmatched until a later run gets an answer.
- Search: Äx `/v2/search/?q=` returns offer-style rows mixed with music. CDON `/s?q=` renders no products; its script POSTs to `search-bff.cdon.se/search/v2/result`, and `BrowserFetcher.search` keeps that response from the page load. Never call that API directly. Most CDON hits are marketplace listings without `preset_media_format`, and CDON never returns an empty result.

## Pages and endpoints

- `/` main page: in-stock offers under the hardcoded caps (BD ≤ €15, 4K ≤ €20), minus movies owned on Blu-ray/UHD; wished movies are badged and a link counts wishlist offers. Query params `max_bd`, `max_4k` (euros), `format=bd|4k`, `store=ax|cdon|mymovies`, `condition=new|used`, `q`.
- `/in-stock`: wishlist offers in stock (accepted formats, any price, deals marked).
- `/box-sets` (in-stock box sets, any price), `/wishlist` (read-only, offers and searches per wish), `/queue` (manual TMDB matching), `/ignored`, `/products/<id>` (price history), `/status`. `/watchlist` redirects to `/wishlist`.
- `POST /api/v2/products/<id>/{ignore|unignore}`; `POST /api/v2/products/<id>/wish` (forwards to moviecatalog `POST /api/wants`); `POST /api/v2/products/<id>/match` with `{"tmdb_id": int|null}`; `GET /api/v2/tmdb/search?q=`.
- `GET /api/v2/offers?tmdb_id=…` (repeatable): read API for moviecatalog; shape fixed by its SPEC.md.

## Project Patterns

- **Package manager**: `uv` only (`uv run`, `uv sync`). Python 3.15 (`.python-version`, `requires-python`, ruff/mypy targets and the Docker base image move together).
- **Types**: strict mypy on `src`; ruff with 100-char lines and C901 complexity 10. `ruff format` also formats code blocks in `docs/*.md`.
- **Database**: sync SQLModel over SQLite. `CatalogModel` has its own metadata. Schema changes go through `catalog/db.py::MIGRATIONS` with a new version number; never silence schema errors.
- **Money**: integer cents everywhere; `euros` Jinja filter for display.
- **Timestamps**: naive UTC in the database (`importer.utc_naive`). Model fields must be typed `pydantic.NaiveDatetime`, not `datetime`: SQLModel ≥ 0.0.49 maps bare `datetime` to a tz-aware column that rejects naive values.
- **Templates**: Jinja; excluded from prettier (it splits `{% %}` tags).
- **Fixtures**: gzip page captures under `tests/fixtures/<store>/` with a README per store. Unit tests never touch the network; `tests/integration/test_live_stores.py` does. Web tests use FastAPI's `TestClient`, which needs `httpx2` (not `httpx`).
- **Docker**: `python:*-slim-trixie` base; `libatomic1` is installed explicitly because Playwright's bundled Node needs it. uv is pinned to an exact version in both the Dockerfile and CI.
- **CI**: `.github/workflows/python-ci.yml` pins actions to exact versions (`astral-sh/setup-uv` has no floating major tags) and reads Python from `.python-version`.
- **Politeness**: one listing fetch per page, 2 s delay, a browser-identifying User-Agent for CDON and MyMovies only because those sites require a browser.

## Environment Variables

See `.env.example`. Key ones: `TMDB_API_KEY` (matching skipped without it),
`JEV_API_KEY` (box-set gate and Jev match decisions; 1Password `op://Development/Jev API/credential`), `JEV_MODEL` (pinned, default `jev-1.14.0`),
`MOVIECATALOG_URL` (sync, wish action; unset = no owned filtering or searches),
`SEARCH_DAILY_CAP` (search requests per store per 24 h),
`SEARCH_MIN_INTERVAL_HOURS` (re-search gap per wish and store, default 24),
`DB_PATH` (`./data/catalog.db`), `RAW_DIR`, `STORES`, `MAX_PAGES_PER_CATEGORY`,
`RUN_SCHEDULER` (in-process daily refresh; leave off when host cron runs
`refresh`), `SCHEDULER_INTERVAL_HOURS`.

## LLM Guidelines

Shared conventions come from the `llm-shared` MCP server. Key rules it carries:

- Python: uv, ruff, strict mypy
- Shell: use `rg` instead of `grep`, `fd` instead of `find`

When a store breaks, follow `ai-docs/crawler-investigation.md`.
