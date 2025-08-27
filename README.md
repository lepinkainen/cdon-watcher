# CDON Blu-ray Price Tracker 🎬

A Docker/Podman-based price tracking system for Blu-ray and 4K Blu-ray movies on CDON.fi. Features automated price monitoring, alerts, and a web dashboard.

## Features

- 🕷️ **JavaScript-aware scraping** using Playwright
- 💾 **SQLite database** for price history and tracking
- 📉 **Automatic price drop detection** with alerts
- 👀 **Watchlist system** with target prices
- 🌐 **Web dashboard** for easy monitoring
- 📧 **Email & Discord notifications** for price drops
- 🐳 **Docker/Podman support** for easy deployment

## Quick Start

### Prerequisites

**For macOS (Development):**

```bash
brew install podman
brew install podman-compose
```

**For Linux (Production):**

```bash
# Docker is usually pre-installed, or:
curl -fsSL https://get.docker.com | sh
```

### Installation

1. **Clone or navigate to the project:**

```bash
cd /Users/shrike/projects/cdon-watcher
```

2. **Copy and configure environment variables:**

```bash
cp .env.example .env
# Edit .env with your settings (optional for email/Discord notifications)
```

3. **Make scripts executable:**

```bash
chmod +x scripts/*.sh
```

### Running on macOS with Podman

```bash
# Start development environment
./scripts/run-dev.sh

# Or manually:
podman machine start  # If not already running
podman-compose up -d
```

### Running on Linux with Docker

```bash
# Start production environment
./scripts/run-prod.sh

# Or manually:
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

## Usage

### Initial Crawl

Populate your database with movies:

```bash
# Using compose
podman-compose run --rm crawler

# Or directly
podman run --rm -v ./data:/app/data cdon-tracker python monitor.py crawl
```

### Access Web Dashboard

Open <http://localhost:8080> in your browser

### Monitor Prices

The monitor service runs automatically in the background, checking prices every 6 hours (configurable).

### View Logs

```bash
# All services
podman-compose logs -f

# Specific service
podman-compose logs -f monitor
podman-compose logs -f web
```

## Configuration

Edit `.env` file for customization:

```env
# Email notifications
EMAIL_ENABLED=true
EMAIL_FROM=your-email@gmail.com
EMAIL_TO=your-email@gmail.com
EMAIL_PASSWORD=your-app-password
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587

# Discord webhook
DISCORD_WEBHOOK=https://discord.com/api/webhooks/...

# Crawler settings
MAX_PAGES_PER_CATEGORY=5
CHECK_INTERVAL_HOURS=6
```

## Project Structure

```
cdon-watcher/
├── cdon_scraper_v2.py        # Hybrid scraper orchestrator
├── listing_crawler.py        # Playwright-based listing crawler  
├── product_parser.py         # Pure Python product parser
├── monitor.py                # Price monitor & web app
├── Dockerfile                # Container definition
├── docker-compose.yml        # Service orchestration
├── docker-compose.override.yml  # Dev overrides
├── docker-compose.prod.yml   # Production config
├── requirements.txt          # Python dependencies
├── nginx.conf               # Production web server
├── .env.example             # Environment template
├── data/                    # Database storage
│   └── cdon_movies.db      # SQLite database
├── config/                  # Configuration files
└── scripts/                 # Helper scripts
    ├── build.sh            # Build container
    ├── run-dev.sh          # Start development
    ├── run-prod.sh         # Start production
    ├── backup.sh           # Backup data
    └── migrate-to-vps.sh   # Deploy to VPS
```

## API Endpoints

When the web service is running:

- `GET /` - Web dashboard
- `GET /api/stats` - Database statistics
- `GET /api/alerts` - Recent price alerts
- `GET /api/deals` - Best current deals
- `GET /api/watchlist` - Your watchlist
- `GET /api/search?q=query` - Search movies
- `POST /api/watchlist` - Add to watchlist

## Backup & Restore

### Create Backup

```bash
./scripts/backup.sh
```

### Restore from Backup

```bash
tar -xzf backups/cdon_backup_TIMESTAMP.tar.gz
```

## Migrating to Production VPS

```bash
# Run migration script
./scripts/migrate-to-vps.sh

# Follow the prompts to transfer to your VPS
```

## Troubleshooting

### Podman Machine Issues (macOS)

```bash
podman machine stop
podman machine rm
podman machine init --cpus 2 --memory 4096
podman machine start
```

### Container Can't Access Website

- Check internet connectivity
- Verify Playwright installation: `podman exec cdon-web playwright --version`
- Check logs: `podman-compose logs web`

### Database Lock Issues

```bash
# Stop all services
podman-compose down
# Remove lock if exists
rm data/cdon_movies.db-journal
# Restart
podman-compose up -d
```

## Development

### Running Without Container

```bash
# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Run directly
python monitor.py web       # Start web dashboard
python monitor.py crawl     # Run crawler
python monitor.py monitor   # Run price monitor
```

### Modifying Scraper Logic

Edit the hybrid scraper components and restart containers:

```bash
podman-compose restart
```

## Security Notes

- Database is stored locally in `./data/`
- No credentials are stored in the image
- Email passwords should use app-specific passwords
- Container runs as non-root user
- SSL/HTTPS support included for production

## License

MIT License - Feel free to modify and use as needed.

## Support

For issues or questions, check the logs first:

```bash
podman-compose logs -f
```

## TODO

- [ ] Add more Finnish retailers (Verkkokauppa, Gigantti)
- [ ] Price prediction based on historical data
- [ ] RSS feed for price drops
- [ ] Mobile app notifications
- [ ] Import watchlist from IMDb/Letterboxd
