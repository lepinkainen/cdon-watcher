# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Essential Commands

### Development Environment Setup

```bash
# Install dependencies using uv (recommended)
uv sync --extra test
uv run playwright install chromium

# Alternative: Traditional pip/venv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### Testing Commands

```bash
# Fast unit tests (no network)
uv run pytest test_basic.py -v

# Test individual components
uv run python test_hybrid.py product   # ProductParser only
uv run python test_hybrid.py listing   # ListingCrawler only  
uv run python test_hybrid.py hybrid    # Full workflow

# Quick URL testing
uv run python test_single_url.py "https://cdon.fi/tuote/movie-url/"

# Integration tests with real pages (slow)
uv run pytest test_parser.py -v --timeout=120

# Manage test cases
uv run python add_test_case.py list
uv run python add_test_case.py add --url "..." --title "Movie Title" --price-min 20 --price-max 40
```

### Container Management

- **Build**: `./scripts/build.sh` (auto-detects Podman/Docker)
- **Development**: `./scripts/run-dev.sh` (macOS with Podman)
- **Production**: `./scripts/run-prod.sh` (Linux with Docker)

### Core Application Commands

```bash
# Run hybrid scraper (recommended)
uv run python cdon_scraper_v2.py

# Container-based crawling
podman-compose --profile crawler run --rm crawler

# Monitor prices (runs automatically in background)
python monitor.py monitor

# Start web dashboard
python monitor.py web

# View logs
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
- **Testing**: `test_*.py`, `conftest.py`, `test_data.json`, `add_test_case.py`
- **Configuration**: `pyproject.toml` (uv), `requirements.txt` (pip), `.env`
- **Containers**: `docker-compose.yml`, `docker-compose.override.yml`, `docker-compose.prod.yml`
- **Scripts**: `scripts/` (build/run helpers)
- **Data**: `data/` (SQLite database storage, volume mounted in containers)

## Development Notes

- **Title extraction fix**: Resolved "vihdoin arki" promotional text extraction issue
- **Performance**: Hybrid approach ~10x faster than pure Playwright
- **Testing**: Comprehensive test suite with real URL validation
- **Maintenance**: Easy test case management, JSON-based configuration
- always use `uv run python` to run code

- always run the web dashboard in a container. rebuild and restart the container when necessary