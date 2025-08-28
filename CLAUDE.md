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

#### **Hybrid Scraper Architecture (v2)**

- **listing_crawler.py**: Playwright-based category page crawler (collects product URLs)
- **product_parser.py**: Pure Python product page parser (extracts title/price via requests + BeautifulSoup)  
- **cdon_scraper_v2.py**: Orchestrator combining both parsers + database operations
- **monitor.py**: Price monitoring daemon and Flask web dashboard
- **SQLite database**: Stores movies, price history, and watchlist data

### Service Architecture

- **web service**: Flask dashboard (port 8080) with API endpoints
- **monitor service**: Background price checker (runs every 6 hours)
- **crawler service**: Hybrid scraper for database population

### Key Technical Details

- **Hybrid approach**: Playwright for JavaScript-heavy listing pages, pure Python for fast product parsing
- **Anti-bot protection**: Stealth browser settings, realistic headers, rate limiting
- **Anti-"vihdoin arki" logic**: Filters promotional text that was corrupting title extraction
- **SQLite database**: movies, price_history, watchlist, alerts tables
- **Flask web API**: `/api/stats`, `/api/alerts`, `/api/deals`, `/api/watchlist`, `/api/search`
- **Email/Discord notifications**: Price drop and target price alerts
- **Container orchestration**: docker-compose with dev/prod variants

### Environment Configuration

- **Python project management**: Uses `uv` (recommended) or traditional pip/venv
- **Dependencies**: Playwright (listing), requests+BeautifulSoup (products), Flask, pytest
- **Configuration**: Environment variables in `.env` file
- **Database path**: `/app/data/cdon_movies.db` in containers, configurable locally
- **Test data**: JSON-based test case management in `test_data.json`

### Data Flow

1. **ListingCrawler** (Playwright) scrapes category pages → collects product URLs
2. **ProductParser** (HTTP) fetches individual product pages → extracts title/price/format  
3. **CDONScraper** orchestrates workflow → saves to SQLite database
4. **Monitor service** checks for price changes → triggers alerts
5. **Web dashboard** serves data via Flask API and HTML interface

## File Structure Notes

- **Core scraper**: `listing_crawler.py`, `product_parser.py`, `cdon_scraper_v2.py`
- **Testing**: `tests/` (unit + integration), `conftest.py`, `test_data.json`, `add_test_case.py`
- **Configuration**: `pyproject.toml` (single dependency source), `.env`
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
- **Database path**: Uses `CONFIG["db_path"]` from `config.py`, typically `data/cdon_movies.db`
- **Hybrid architecture**: Playwright for dynamic pages, requests+BeautifulSoup for static parsing
- **CLI interface**: All functionality accessible via `uv run python -m cdon_watcher [command]`

### Key Implementation Details

- **Title extraction fix**: Resolved "vihdoin arki" promotional text extraction issue
- **Performance**: Hybrid approach ~10x faster than pure Playwright  
- **Anti-bot protection**: Stealth browser settings, realistic headers, rate limiting
- **Testing**: JSON-based test case management (`add_test_case.py`), real URL validation

### LLM Assistant Guidelines

Refer to `llm-shared/` submodule for:
- **General development**: `project_tech_stack.md` (project management, validation)
- **Python conventions**: `languages/python.md` (libraries, tools, patterns)
- **Shell tools**: `shell_commands.md` (use `rg` instead of `grep`, `fd` instead of `find`)
- **GitHub workflow**: `GITHUB.md` (issue management)
