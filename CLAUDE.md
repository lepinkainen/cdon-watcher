# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Essential Commands

### Development Environment Setup

```bash
# Quick setup (recommended)
task install          # Install all dependencies + playwright

# Manual setup using uv (recommended)
uv sync --extra test --extra dev
uv run playwright install chromium

# Environment configuration
cp .env.example .env   # Copy and edit with your settings (optional for notifications)

# Alternative: Traditional pip/venv (uses pyproject.toml)
python3 -m venv venv
source venv/bin/activate
pip install -e .[test,dev]
playwright install chromium
```

### Build and Quality Checks

```bash
# Complete build pipeline (setup, test, lint)
task build

# Individual quality checks
task test              # Fast unit tests
task test-integration  # Slow integration tests (requires network)
task lint              # ruff + mypy

# CI-friendly commands
task build-ci          # Build without tests
task test-ci           # Tests with coverage
```

### Testing Commands

```bash
# Fast unit tests (no network, preferred for development)
task test
# or manually: PYTHONPATH=./src uv run pytest tests/unit/ -v --timeout=30

# Integration tests (slow, real network requests)
task test-integration
task test-hybrid       # Test the hybrid scraper workflow specifically

# Legacy testing interfaces (maintained for compatibility)
uv run python tests/integration/test_legacy_hybrid_workflow.py [product|listing|hybrid]
uv run python tests/integration/test_single_url_processing.py "https://cdon.fi/tuote/movie-url/"

# All tests
task test-all

# Test data management
uv run python -m cdon_watcher.add_test_case list                    # List test cases
uv run python -m cdon_watcher.add_test_case add --url URL --title TITLE  # Add test case
```

### Container Management

- **Build**: `task docker-build` or `./scripts/build.sh` (auto-detects Podman/Docker)
- **Development**: `task docker-dev` or `./scripts/run-dev.sh` (macOS with Podman)
- **Production**: `task docker-prod` or `./scripts/run-prod.sh` (Linux with Docker)
- **Stop containers**: `task docker-stop`
- **View logs**: `task docker-logs`

### Core Application Commands

```bash
# Module-based execution (recommended)
uv run python -m cdon_watcher crawl    # Initial crawl
uv run python -m cdon_watcher monitor  # Price monitoring
uv run python -m cdon_watcher web      # Web dashboard

# Task-based shortcuts
task crawl             # Container-based crawling
task monitor           # Local monitoring service
task web               # Local web dashboard

# Container-based execution
podman-compose --profile crawler run --rm crawler
podman-compose logs -f monitor
podman-compose logs -f web
```

## Architecture Overview

**Hybrid Python web scraping application** that tracks Blu-ray movie prices on CDON.fi using a two-parser architecture:

### Core Components

#### **Hybrid Scraper Architecture (v3 - FastAPI+SQLModel)**

- **listing_crawler.py**: Playwright-based category page crawler (collects product URLs)
- **product_parser.py**: Pure Python product page parser (extracts title/price via requests + BeautifulSoup)
- **cdon_scraper.py**: Orchestrator combining both parsers + async SQLModel database operations
- **monitoring_service.py**: Price monitoring service using SQLModel repository pattern
- **web/app.py & web/routes.py**: FastAPI web dashboard with async API endpoints
- **SQLModel database**: Type-safe async database operations with proper relationships

### Service Architecture

- **web service**: FastAPI dashboard (port 8080) with async API endpoints and Jinja2 templates
- **monitor service**: Background price checker using SQLModel repository pattern (runs every 6 hours)
- **crawler service**: Hybrid scraper with async SQLModel database operations

### Key Technical Details

- **Hybrid approach**: Playwright for JavaScript-heavy listing pages, pure Python for fast product parsing
- **Anti-bot protection**: Stealth browser settings, realistic headers, rate limiting
- **Anti-"vihdoin arki" logic**: Filters promotional text that was corrupting title extraction
- **SQLModel database**: Type-safe async operations with SQLAlchemy + aiosqlite backend
- **FastAPI web API**: `/api/stats`, `/api/alerts`, `/api/deals`, `/api/watchlist`, `/api/search` with Pydantic response models
- **Database models**: `Movie`, `PriceHistory`, `Watchlist`, `PriceAlert`, `IgnoredMovie` with proper relationships
- **Email/Discord notifications**: Price drop and target price alerts
- **Container orchestration**: docker-compose with dev/prod variants

### Environment Configuration

- **Python project management**: Uses `uv` (recommended) or traditional pip/venv
- **Dependencies**: FastAPI, SQLModel, Playwright (listing), requests+BeautifulSoup (products), Jinja2, pytest
- **Configuration**: Environment variables in `.env` file (copy from `.env.example`)
- **Database path**: `/app/data/cdon_movies.db` in containers, configurable locally via `CONFIG["db_path"]`
- **Test data**: JSON-based test case management via `add_test_case.py` (stored in `src/cdon_watcher/test_data.json`)

### Data Flow

1. **ListingCrawler** (Playwright) scrapes category pages → collects product URLs
2. **ProductParser** (HTTP) fetches individual product pages → extracts title/price/format
3. **CDONScraper** orchestrates workflow → saves to SQLModel database using async operations
4. **PriceMonitor** service checks for price changes → triggers alerts via SQLModel repository
5. **FastAPI dashboard** serves data via type-safe API endpoints and Jinja2 templates

## File Structure Notes

- **Core scraper**: `listing_crawler.py`, `product_parser.py`, `cdon_scraper.py` (async SQLModel operations)
- **Database layer**: `database/connection.py`, `database/repository.py`, `models.py`, `schemas.py`
- **Web layer**: `web/app.py` (FastAPI setup), `web/routes.py` (API endpoints), `templates/index.html`
- **Services**: `monitoring_service.py` (price monitoring with SQLModel)
- **CLI**: `cli.py` (command-line interface), `__main__.py` (module entry point)
- **Testing**: `tests/` (unit + integration), `conftest.py`, `add_test_case.py` (test data management)
- **Configuration**: `pyproject.toml` (single dependency source), `Taskfile.yml` (task runner), `.env`
- **Containers**: `docker-compose.yml`, `docker-compose.override.yml`, `docker-compose.prod.yml`
- **Scripts**: `scripts/` (build/run helpers)
- **Data**: `data/` (SQLite database storage, volume mounted in containers)

## Development Notes

### Code Quality and Conventions

- **Package management**: Use `uv` exclusively - all commands should be `uv run python` or `task` shortcuts
- **Testing strategy**: Fast unit tests for development (`task test`), integration tests for validation
- **Build pipeline**: Always run `task build` before completing tasks (includes tests + linting)
- **Web dashboard**: Always run in containers - rebuild and restart when necessary

### Project-Specific Patterns

- **Module structure**: Code organized in `src/cdon_watcher/` with proper `__main__.py` entry point
- **Database operations**: Async SQLModel with repository pattern in `database/repository.py`
- **Type safety**: SQLModel models in `models.py`, Pydantic schemas in `schemas.py`
- **Database path**: Uses `CONFIG["db_path"]` from `config.py`, typically `data/cdon_movies.db`
- **Hybrid architecture**: Playwright for dynamic pages, requests+BeautifulSoup for static parsing
- **CLI interface**: All functionality accessible via `uv run python -m cdon_watcher [command]`

### Key Implementation Details

- **Migration completed**: Successfully migrated from Flask+pure SQL to FastAPI+SQLModel
- **Type safety**: Full type checking with SQLModel relationships and Pydantic validation
- **Async operations**: All database operations are async for better performance
- **Title extraction fix**: Resolved "vihdoin arki" promotional text extraction issue
- **Performance**: Hybrid approach ~10x faster than pure Playwright
- **Anti-bot protection**: Stealth browser settings, realistic headers, rate limiting
- **Testing patterns**:
  - Unit tests in `tests/unit/` (fast, no network)
  - Integration tests in `tests/integration/` (slow, real network requests)
  - JSON-based test case management (`add_test_case.py`)
  - Async test fixtures with temporary databases (`conftest.py`)

### LLM Assistant Guidelines

Refer to `llm-shared/` submodule for:

- **General development**: `project_tech_stack.md` (project management, validation)
- **Python conventions**: `languages/python.md` (libraries, tools, patterns)
- **Shell tools**: `shell_commands.md` (use `rg` instead of `grep`, `fd` instead of `find`)
- **GitHub workflow**: `GITHUB.md` (issue management)
