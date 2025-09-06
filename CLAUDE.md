# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Essential Commands

### Development Environment Setup

```bash
# Quick setup (recommended) - installs all dependencies + playwright
task install

# Manual setup using uv (recommended)
uv sync --extra test --extra dev
uv run playwright install chromium

# Environment configuration (optional for notifications)
cp .env.example .env   # Edit with TMDB_API_KEY, email/Discord settings
```

### Build and Quality Checks

```bash
# Complete build pipeline (setup, test, lint) - ALWAYS run before completing tasks
task build

# Individual quality checks
task test              # Fast unit tests (no network)
task test-integration  # Slow integration tests (requires network)
task lint              # ruff check + mypy type checking

# CI-friendly commands
task build-ci          # Build without tests
task test-ci           # Tests with coverage reporting
```

### Testing Commands

```bash
# Fast unit tests (no network, preferred for development)
task test
# Manual: PYTHONPATH=./src uv run pytest tests/unit/ --timeout=30

# Integration tests (slow, requires real network requests)
task test-integration
task test-hybrid       # Test the hybrid scraper workflow specifically
task test-all          # Run all tests (unit + integration)

# Test data management (JSON-based test cases)
uv run python -m cdon_watcher.add_test_case list                    # List test cases
uv run python -m cdon_watcher.add_test_case add --url URL --title TITLE  # Add test case

# Legacy testing interfaces (for specific debugging)
uv run python tests/integration/test_single_url_processing.py "https://cdon.fi/tuote/movie-url/"
```

### Container Management

```bash
# Container operations (auto-detects Podman/Docker)
task docker-build     # Build containers
task docker-dev       # Run development environment (macOS with Podman)
task docker-prod      # Run production environment (Linux with Docker)
task docker-stop      # Stop all containers
task docker-logs      # View container logs

# Alternative scripts (platform detection built-in)
./scripts/build.sh    # Build containers
./scripts/run-dev.sh  # Development mode
./scripts/run-prod.sh # Production mode
```

### Core Application Commands

```bash
# Module-based execution (local development)
uv run python -m cdon_watcher crawl    # Initial crawl (fast mode)
uv run python -m cdon_watcher monitor  # Price monitoring service
uv run python -m cdon_watcher web      # Web dashboard
uv run python -m cdon_watcher update-scan  # Update existing movies

# Task-based shortcuts (preferred)
task crawl             # Container-based crawling (fast mode)
task crawl-moderate    # Moderate speed crawl (local)
task crawl-slow        # Slow speed crawl (local)
task monitor           # Local monitoring service
task web               # Local web dashboard

# Container-based execution (production-like)
podman-compose --profile crawler run --rm crawler   # One-time crawl
podman-compose up web monitor                        # Start services
podman-compose logs -f monitor                       # View monitor logs
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

- **Hybrid approach**: Playwright for JavaScript-heavy listing pages, pure Python (requests+BeautifulSoup) for fast product parsing (~10x faster)
- **Anti-bot protection**: Stealth browser settings, realistic headers, rate limiting
- **Anti-"vihdoin arki" logic**: Filters promotional text that was corrupting title extraction
- **SQLModel database**: Type-safe async operations with SQLAlchemy + aiosqlite backend
- **FastAPI web API**: `/api/stats`, `/api/alerts`, `/api/deals`, `/api/watchlist`, `/api/search` with Pydantic response models
- **Database models**: `Movie`, `PriceHistory`, `Watchlist`, `PriceAlert`, `IgnoredMovie` with proper SQLModel relationships
- **TMDB integration**: Movie posters and metadata fetched via TMDB API (requires `TMDB_API_KEY`)
- **Speed modes**: Three scan modes (fast/moderate/slow) configurable via `SCAN_MODE` environment variable
- **Container orchestration**: docker-compose with dev/prod variants, auto-detects Podman/Docker

### Environment Configuration

- **Python project management**: Uses `uv` (recommended) - defined in `pyproject.toml`
- **Core dependencies**: FastAPI, SQLModel, Playwright, requests+BeautifulSoup, Jinja2, aiosqlite
- **Configuration**: Environment variables in `.env` file (copy from `.env.example`), key vars:
  - `TMDB_API_KEY`: Required for movie posters/metadata
  - `DB_PATH`: Database location (`/app/data/cdon_movies.db` in containers)
  - `SCAN_MODE`: Speed control (fast/moderate/slow)
  - Email/Discord notification settings (optional)
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
- **Testing strategy**: Fast unit tests for development (`task test`), integration tests for validation (`task test-integration`)
- **Build pipeline**: **ALWAYS** run `task build` before completing tasks (includes setup, tests, and linting)
- **Type checking**: Strict mypy configuration with SQLModel support - all functions must be typed
- **Code formatting**: Ruff for linting and formatting with 100-char line length

### Project-Specific Patterns

- **Module structure**: Code organized in `src/cdon_watcher/` with proper `__main__.py` entry point
- **Database operations**: Async SQLModel with repository pattern in `database/repository.py`
- **Type safety**: SQLModel models in `models.py`, Pydantic response schemas in `schemas.py`
- **Database path**: Uses `CONFIG["db_path"]` from `config.py`, typically `data/cdon_movies.db`
- **Hybrid architecture**: Playwright (`listing_crawler.py`) for dynamic pages, requests+BeautifulSoup (`product_parser.py`) for static parsing
- **CLI interface**: All functionality accessible via `uv run python -m cdon_watcher [command]`
- **Web dashboard**: FastAPI with Jinja2 templates in `web/` directory, async API endpoints

### Key Implementation Details

- **Migration completed**: Successfully migrated from Flask+pure SQL to FastAPI+SQLModel
- **Type safety**: Full type checking with SQLModel relationships and Pydantic validation
- **Async operations**: All database operations are async for better performance
- **Title extraction fix**: Resolved "vihdoin arki" promotional text extraction issue corrupting titles
- **Performance**: Hybrid approach ~10x faster than pure Playwright scraping
- **Anti-bot protection**: Stealth browser settings, realistic headers, rate limiting
- **Testing architecture**:
  - Unit tests (`tests/unit/`): Fast, no network, use temporary databases via `conftest.py`
  - Integration tests (`tests/integration/`): Slow, real network requests, test full workflows
  - JSON-based test case management: `add_test_case.py` manages `test_data.json` for regression testing
  - Async test fixtures with SQLModel support

### Critical Implementation Notes

- **TMDB Integration**: Movie posters and metadata require `TMDB_API_KEY` environment variable
- **Test Management**: Use `add_test_case.py` to manage test URLs in `test_data.json` for regression testing
- **Container Platform Detection**: Scripts auto-detect Podman (macOS development) vs Docker (Linux production)
- **Database**: SQLite at `data/cdon_movies.db`, async operations via SQLModel repository pattern
- **Speed Control**: Three scan modes (fast/moderate/slow) via `SCAN_MODE` environment variable
- **Web Testing**: **Always** use Playwright to verify web functionality after changes - required by development workflow

### LLM Assistant Guidelines

Refer to `llm-shared/` submodule for additional conventions:

- **General development**: `project_tech_stack.md` (project management, validation patterns)
- **Python conventions**: `languages/python.md` (modern Python libraries, tools, patterns)
- **Shell tools**: `shell_commands.md` (use `rg` instead of `grep`, `fd` instead of `find`)
- **GitHub workflow**: `GITHUB.md` (issue management, PR creation)
