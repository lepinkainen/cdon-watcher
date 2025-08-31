# Setup and Installation Guide

This guide covers the installation and setup of CDON Watcher for both development and production environments.

## Prerequisites

### System Requirements

- **Python**: 3.11 or higher
- **Container Runtime**: Docker or Podman
- **Git**: For cloning the repository
- **Internet Connection**: Required for scraping and package downloads

### Hardware Requirements

- **RAM**: Minimum 2GB, recommended 4GB+
- **Storage**: 500MB for application, plus space for database and posters
- **Network**: Stable internet connection for web scraping

## Quick Start

### Option 1: Containerized Setup (Recommended)

#### macOS with Podman

```bash
# 1. Install prerequisites
brew install podman podman-compose

# 2. Clone repository
git clone https://github.com/lepinkainen/cdon-watcher.git
cd cdon-watcher

# 3. Copy environment configuration
cp .env.example .env

# 4. Make scripts executable
chmod +x scripts/*.sh

# 5. Start development environment
./scripts/run-dev.sh
```

#### Linux with Docker

```bash
# 1. Install Docker
curl -fsSL https://get.docker.com | sh
sudo systemctl start docker

# 2. Clone repository
git clone https://github.com/lepinkainen/cdon-watcher.git
cd cdon-watcher

# 3. Copy environment configuration
cp .env.example .env

# 4. Start production environment
./scripts/run-prod.sh
```

### Option 2: Local Development Setup

#### Using uv (Recommended)

```bash
# 1. Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Clone repository
git clone https://github.com/lepinkainen/cdon-watcher.git
cd cdon-watcher

# 3. Install dependencies
uv sync --extra test --extra dev

# 4. Install Playwright browsers
uv run playwright install chromium

# 5. Copy environment configuration
cp .env.example .env

# 6. Run the application
uv run python -m cdon_watcher web
```

#### Using pip/venv (Traditional)

```bash
# 1. Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 2. Clone repository
git clone https://github.com/lepinkainen/cdon-watcher.git
cd cdon-watcher

# 3. Install dependencies
pip install -e .[test,dev]

# 4. Install Playwright browsers
playwright install chromium

# 5. Copy environment configuration
cp .env.example .env

# 6. Run the application
python -m cdon_watcher web
```

## Environment Configuration

### Basic Configuration

Create a `.env` file in the project root:

```env
# Database
DB_PATH=./data/cdon_movies.db

# Web Server
API_HOST=127.0.0.1
API_PORT=8080
API_DEBUG=false

# Scraping
CHECK_INTERVAL_HOURS=6
MAX_PAGES_PER_CATEGORY=10

# Notifications (optional)
EMAIL_ENABLED=false
DISCORD_WEBHOOK=

# TMDB Integration (optional)
TMDB_API_KEY=
```

### Advanced Configuration

```env
# Database Configuration
DB_PATH=./data/cdon_movies.db
POSTER_DIR=./data/posters

# Web Server Configuration
API_HOST=0.0.0.0
API_PORT=8080
API_DEBUG=true

# Scraping Configuration
CHECK_INTERVAL_HOURS=6
MAX_PAGES_PER_CATEGORY=10
REQUEST_TIMEOUT=30
MAX_RETRIES=3

# Email Notifications
EMAIL_ENABLED=true
EMAIL_FROM=your-email@gmail.com
EMAIL_TO=your-email@gmail.com
EMAIL_PASSWORD=your-app-password
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587

# Discord Notifications
DISCORD_WEBHOOK=https://discord.com/api/webhooks/YOUR_WEBHOOK_ID/YOUR_WEBHOOK_TOKEN

# TMDB Integration
TMDB_API_KEY=your-tmdb-api-key

# Development Settings
ENABLE_QUERY_LOGGING=false
LOG_LEVEL=INFO
```

## First-Time Setup

### 1. Database Initialization

The database is automatically created when you first run the application. No manual initialization is required.

### 2. Initial Data Population

Populate your database with movie data:

```bash
# Using containers
podman-compose run --rm crawler

# Or locally
uv run python -m cdon_watcher crawl --max-pages 5
```

### 3. Access Web Dashboard

Once running, access the web dashboard at:

- **Local**: <http://localhost:8080>
- **Container**: <http://localhost:8080>

## Development Environment Setup

### IDE Configuration

#### VS Code

1. Install recommended extensions:
   - Python
   - Pylance
   - Ruff
   - Docker

2. Configure Python interpreter:
   - Select the virtual environment or uv environment

3. Enable format on save:

   ```json
   {
     "python.formatting.provider": "none",
     "editor.codeActionsOnSave": {
       "source.fixAll.ruff": "explicit"
     }
   }
   ```

### Testing Setup

```bash
# Install test dependencies
uv sync --extra test

# Run tests
uv run pytest

# Run with coverage
uv run pytest --cov=cdon_watcher

# Run integration tests
uv run pytest tests/integration/
```

### Code Quality Tools

```bash
# Linting
uv run ruff check .

# Type checking
uv run mypy src/

# Format code
uv run ruff format .
```

## Production Deployment

### Docker Compose Production

```bash
# 1. Configure production environment
cp .env.example .env.prod
# Edit .env.prod with production settings

# 2. Use production compose file
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# 3. Check logs
docker-compose logs -f
```

### VPS Deployment

```bash
# 1. Prepare VPS (Ubuntu/Debian)
sudo apt update
sudo apt install docker.io docker-compose
sudo systemctl enable docker

# 2. Run migration script
./scripts/migrate-to-vps.sh

# 3. Follow prompts to transfer data and configuration
```

### Nginx Configuration

For production with nginx reverse proxy:

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Static files
    location /static/ {
        alias /path/to/cdon-watcher/src/cdon_watcher/static/;
        expires 1y;
    }

    # Posters
    location /posters/ {
        alias /path/to/cdon-watcher/data/posters/;
        expires 30d;
    }
}
```

## Troubleshooting Setup Issues

### Container Issues

#### Podman on macOS

```bash
# Reset Podman machine
podman machine stop
podman machine rm
podman machine init --cpus 2 --memory 4096
podman machine start
```

#### Docker Permission Issues

```bash
# Add user to docker group
sudo usermod -aG docker $USER
# Logout and login again
```

### Python Environment Issues

#### uv Installation Issues

```bash
# Manual uv installation
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.cargo/bin:$PATH"
```

#### Virtual Environment Issues

```bash
# Recreate virtual environment
rm -rf venv
python3 -m venv venv
source venv/bin/activate
pip install -e .[test,dev]
```

### Network Issues

#### Playwright Browser Installation

```bash
# Force reinstall browsers
uv run playwright install --force chromium

# Or manually
cd ~/.cache/ms-playwright
rm -rf *
uv run playwright install chromium
```

#### SSL Certificate Issues

```bash
# Disable SSL verification (not recommended for production)
export REQUESTS_CA_BUNDLE=""
# Or install certificates
sudo apt install ca-certificates
```

### Database Issues

#### Permission Issues

```bash
# Fix database permissions
chmod 644 data/cdon_movies.db
chmod 755 data/
```

#### Database Lock Issues

```bash
# Stop all services
podman-compose down

# Remove lock file
rm -f data/cdon_movies.db-journal

# Restart services
podman-compose up -d
```

## Backup and Restore

### Automated Backup

```bash
# Run backup script
./scripts/backup.sh
```

### Manual Backup

```bash
# Backup database and configuration
tar -czf backup_$(date +%Y%m%d_%H%M%S).tar.gz \
    data/ \
    .env \
    docker-compose.yml
```

### Restore from Backup

```bash
# Extract backup
tar -xzf backup_filename.tar.gz

# Restart services
podman-compose up -d
```

## Performance Optimization

### Container Optimization

```bash
# Use production compose
docker-compose -f docker-compose.prod.yml up -d

# Monitor resource usage
docker stats
```

### Database Optimization

```bash
# Analyze database
sqlite3 data/cdon_movies.db "ANALYZE;"

# Vacuum database
sqlite3 data/cdon_movies.db "VACUUM;"
```

### Scraping Optimization

```env
# Reduce check interval for more frequent updates
CHECK_INTERVAL_HOURS=2

# Increase pages for more comprehensive coverage
MAX_PAGES_PER_CATEGORY=20
```

## Security Considerations

### Container Security

- Containers run as non-root user
- Minimal base images used
- No sensitive data in images

### Network Security

- Local access only by default
- Configure firewall rules for production
- Use HTTPS in production

### Data Security

- Database stored locally
- Environment variables for sensitive data
- Regular backups recommended

## Next Steps

After setup is complete:

1. **Access the web dashboard** at <http://localhost:8080>
2. **Run initial crawl** to populate the database
3. **Configure notifications** if desired
4. **Set up watchlist** for price monitoring
5. **Review logs** for any issues

For detailed usage instructions, see the [Usage Guide](03_usage.md).
