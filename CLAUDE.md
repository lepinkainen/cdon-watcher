# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Essential Commands

```bash
# Setup (one-time)
task install                    # Install deps + playwright

# Development workflow
task build                      # ALWAYS run before completing tasks (test + lint)
task test                       # Fast unit tests (no network)
task test-integration           # Slow tests (real network)
task lint-fix                   # Auto-fix linting issues

# Run locally
uv run python -m cdon_watcher web      # Web dashboard at :8080
uv run python -m cdon_watcher crawl    # Initial crawl
uv run python -m cdon_watcher monitor  # Price monitoring service
uv run python -m cdon_watcher crawl-raw --store ax  # Archive Äx offers, no DB writes

# Run single test
PYTHONPATH=./src uv run pytest tests/unit/test_file.py -k "test_name"
```

## Architecture Overview

The multi-store rewrite in `docs/09_multi_store_plan.md` has started with the
standalone raw crawler. `ingestion/archive.py` stores numbered runs and compressed
responses with manifests; `ingestion/stores.py` owns Äx offer discovery;
`ingestion/crawler.py` handles delayed requests and retries. `crawl-raw --store ax`
fetches only offer listing pages and uses a per-store process lock. It returns 1
for incomplete runs, preserving all received responses for later offline parsing.
The parser, importer, and replacement UI are not implemented yet. The architecture
below describes the existing application.

**Hybrid web scraper** tracking Blu-ray prices on CDON.fi with three services:

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│ ListingCrawler  │────▶│  ProductParser   │────▶│   SQLModel DB   │
│  (Playwright)   │     │ (requests+BS4)   │     │  (async ops)    │
│ JS-heavy pages  │     │ ~10x faster      │     │                 │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                                                         │
                    ┌────────────────────────────────────┤
                    ▼                                    ▼
          ┌─────────────────┐              ┌─────────────────────┐
          │  PriceMonitor   │              │   FastAPI Web       │
          │ (every 6 hours) │              │  (/api/* endpoints) │
          └─────────────────┘              └─────────────────────┘
```

### Key Files

| Component | Files                                                           | Purpose               |
| --------- | --------------------------------------------------------------- | --------------------- |
| Scraper   | `listing_crawler.py`, `product_parser.py`, `cdon_scraper.py`    | Hybrid crawling       |
| Database  | `database/connection.py`, `database/repository.py`, `models.py` | Async SQLModel ops    |
| Web       | `web/app.py`, `web/routes.py`                                   | FastAPI + Jinja2      |
| Services  | `monitoring_service.py`, `cli.py`                               | Background monitoring |

### API Endpoints

- `/api/stats` - Dashboard statistics
- `/api/deals` - Price drops (sorted best-to-worst, min €5 diff)
- `/api/search?q=&max_price=&category=` - Search with filters
- `/api/watchlist` - GET/POST/DELETE watchlist
- `/api/cheapest-blurays`, `/api/cheapest-4k-blurays` - Format-specific

## Project Patterns

- **Package manager**: `uv` exclusively (`uv run python`, `uv sync`)
- **Type safety**: SQLModel + strict mypy - all functions must be typed
- **Database ops**: Async repository pattern in `database/repository.py`
- **Config**: Environment vars via `.env` (copy `.env.example`)
- **Linting**: ruff (100-char lines) + mypy

## Environment Variables

```bash
TMDB_API_KEY=xxx          # Required for posters
DB_PATH=./data/cdon_movies.db
SCAN_MODE=fast|moderate|slow
MIN_DEAL_DIFF=5.00        # Min € diff for "deals"
DISCORD_WEBHOOK=xxx       # Optional notifications
```

## Testing

- **Unit tests** (`tests/unit/`): Fast, no network, temp databases via `conftest.py`
- **Integration tests** (`tests/integration/`): Real network, full workflows
- **Test data**: JSON-based via `add_test_case.py` → `test_data.json`

## LLM Guidelines

Shared conventions come from the `llm-shared` MCP server (no longer a
submodule). Key rules it carries:

- Python: uv, ruff, strict mypy
- Shell: use `rg` instead of `grep`, `fd` instead of `find`
- GitHub: never commit to main directly, use feature branches
