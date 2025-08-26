# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Essential Commands

### Container Management
- **Build**: `./scripts/build.sh` (auto-detects Podman/Docker)
- **Development**: `./scripts/run-dev.sh` (macOS with Podman)
- **Production**: `./scripts/run-prod.sh` (Linux with Docker)

### Core Application Commands
```bash
# Initial crawl to populate database
podman-compose run --rm crawler
# or: podman run --rm -v ./data:/app/data cdon-tracker python monitor.py crawl

# Monitor prices (runs automatically in background)
python monitor.py monitor

# Start web dashboard
python monitor.py web

# View logs
podman-compose logs -f monitor
podman-compose logs -f web
```

### Direct Python Development (without containers)
```bash
pip install -r requirements.txt
playwright install chromium
python monitor.py web       # Start web dashboard
python monitor.py crawl     # Run crawler
python monitor.py monitor   # Run price monitor
```

## Architecture Overview

This is a Python-based web scraping application that tracks Blu-ray movie prices on CDON.fi using:

### Core Components
- **cdon_scraper.py**: Main scraper logic using Playwright for JavaScript-aware scraping
- **monitor.py**: Price monitoring daemon and Flask web dashboard
- **SQLite database**: Stores movies, price history, and watchlist data

### Service Architecture
- **web service**: Flask dashboard (port 8080) with API endpoints
- **monitor service**: Background price checker (runs every 6 hours)
- **crawler service**: One-time database population (manual trigger)

### Key Technical Details
- Uses Playwright for scraping JavaScript-rendered content
- SQLite database with movies, price_history, watchlist, and alerts tables
- Flask web API with endpoints: `/api/stats`, `/api/alerts`, `/api/deals`, `/api/watchlist`, `/api/search`
- Email/Discord notifications for price drops
- Container orchestration via docker-compose with dev/prod variants

### Environment Configuration
- All configuration via environment variables in `.env` file
- Database path: `/app/data/cdon_movies.db` in containers
- Configurable check intervals, notification settings, and scraping limits

### Data Flow
1. Crawler scrapes CDON.fi for Blu-ray listings → SQLite
2. Monitor service periodically checks for price changes → triggers alerts
3. Web dashboard serves data via Flask API and HTML interface
4. Users manage watchlists and receive notifications

## File Structure Notes
- `scripts/`: Contains helper scripts for building and running
- `data/`: SQLite database storage (volume mounted in containers)
- `config/`: Configuration files storage
- `docker-compose.yml`: Base service definitions
- `docker-compose.override.yml`: Development overrides
- `docker-compose.prod.yml`: Production configurations with nginx