# Usage Guide

This guide covers how to use CDON Watcher for price monitoring and management of your Blu-ray movie collection.

## Command Line Interface

### Basic Commands

#### Start Web Dashboard

```bash
# Using containers (recommended)
podman-compose up -d web
# Access at http://localhost:8080

# Or locally
uv run python -m cdon_watcher web
```

#### Run Initial Crawl

```bash
# Using containers
podman-compose run --rm crawler

# Or locally with default settings
uv run python -m cdon_watcher crawl

# With custom page limit
uv run python -m cdon_watcher crawl --max-pages 20
```

#### Start Price Monitor

```bash
# Using containers (runs in background)
podman-compose up -d monitor

# Or locally
uv run python -m cdon_watcher monitor
```

### Advanced CLI Usage

#### Crawler Options

```bash
# Limit pages per category
uv run python -m cdon_watcher crawl --max-pages 5

# Custom environment variables
MAX_PAGES_PER_CATEGORY=3 uv run python -m cdon_watcher crawl
```

#### Monitor Options

The monitor runs continuously and checks prices every 6 hours by default. Configure via environment variables:

```bash
# Check every 2 hours
CHECK_INTERVAL_HOURS=2 uv run python -m cdon_watcher monitor

# Enable debug logging
API_DEBUG=true uv run python -m cdon_watcher monitor
```

## Web Dashboard

### Accessing the Dashboard

Once the web service is running, access the dashboard at:

- **Local Development**: <http://localhost:8080>
- **Container**: <http://localhost:8080>

### Dashboard Overview

The main dashboard displays:

- **Statistics Panel**: Total movies, recent alerts, watchlist count
- **Recent Alerts**: Latest price drops and notifications
- **Top Deals**: Movies with biggest price reductions
- **Watchlist**: Your monitored movies with target prices

### Navigation

#### Main Sections

- **Dashboard**: Overview and statistics
- **Movies**: Browse all tracked movies
- **Watchlist**: Manage price targets
- **Alerts**: View price change history
- **Search**: Find specific movies

## Movie Management

### Browsing Movies

#### View All Movies

1. Navigate to the main dashboard
2. Browse the movie grid with pagination
3. Each movie card shows:
   - Movie poster (if available)
   - Title and format (Blu-ray/4K)
   - Current price and price history
   - Last updated timestamp

#### Movie Details

Click on any movie card to view detailed information:

- **Price History Chart**: Visual price trends over time
- **Price Statistics**: Highest, lowest, and average prices
- **Product Information**: Format, availability, product URL
- **Action Buttons**: Add to watchlist, ignore movie

### Search Functionality

#### Basic Search

Use the search bar in the top navigation:

```text
# Search by title
Inception

# Search by format
4K Blu-ray

# Search by price range
under 20
```

#### Advanced Search

The search supports multiple criteria:

- **Title keywords**: Any part of the movie title
- **Format**: "blu-ray", "4k", "4K Blu-ray"
- **Price filters**: "under 20", "over 30", "between 15 25"
- **Availability**: "in stock", "out of stock"

#### Search Results

Search results display:

- Matching movies with relevance ranking
- Price information and availability
- Quick actions (add to watchlist, view details)

## Watchlist Management

### Adding Movies to Watchlist

#### Method 1: From Dashboard

1. Browse or search for a movie
2. Click the movie card
3. Click "Add to Watchlist"
4. Set your target price
5. Click "Add"

#### Method 2: From Movie Details

1. Open movie details page
2. Enter target price in the watchlist section
3. Click "Add to Watchlist"

#### Method 3: Via API

```bash
# Add movie to watchlist
curl -X POST http://localhost:8080/api/watchlist \
  -H "Content-Type: application/json" \
  -d '{"product_id": "MOVIE_ID", "target_price": 25.99}'
```

### Managing Watchlist

#### View Watchlist

1. Navigate to "Watchlist" section
2. View all monitored movies
3. See current vs target prices
4. Check price alerts status

#### Edit Target Price

1. In watchlist view, click edit icon
2. Update target price
3. Save changes

#### Remove from Watchlist

1. In watchlist view, click remove icon
2. Confirm removal

#### Bulk Operations

Use the API for bulk watchlist management:

```bash
# Get current watchlist
curl http://localhost:8080/api/watchlist

# Remove movie from watchlist
curl -X DELETE http://localhost:8080/api/watchlist/MOVIE_ID
```

## Price Alerts

### Alert Types

CDON Watcher generates alerts for:

- **Price Drops**: When a movie price decreases
- **Target Reached**: When current price drops to or below target
- **Back in Stock**: When out-of-stock items become available
- **New Low**: When a movie reaches its lowest recorded price

### Viewing Alerts

#### Recent Alerts Dashboard

- Main dashboard shows last 10 alerts
- Click "View All" to see complete history
- Filter by alert type and date range

#### Alert Details

Each alert includes:

- Movie information and current price
- Previous price and price change amount
- Alert type and timestamp
- Direct link to product page

### Notification Settings

#### Email Notifications

Configure in `.env` file:

```env
EMAIL_ENABLED=true
EMAIL_FROM=your-email@gmail.com
EMAIL_TO=your-email@gmail.com
EMAIL_PASSWORD=your-app-password
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
```

#### Discord Notifications

```env
DISCORD_WEBHOOK=https://discord.com/api/webhooks/YOUR_WEBHOOK_ID/YOUR_WEBHOOK_TOKEN
```

### Managing Alert History

#### Mark as Read

- Alerts are automatically marked as read when viewed
- Use API to manually mark alerts:

```bash
# Mark alert as notified
curl -X PATCH http://localhost:8080/api/alerts/ALERT_ID \
  -H "Content-Type: application/json" \
  -d '{"notified": true}'
```

#### Clear Old Alerts

```bash
# Get alerts older than 30 days
curl "http://localhost:8080/api/alerts?days=30"

# Archive old alerts (manual process)
```

## Data Management

### Ignoring Movies

#### Add to Ignored List

1. Open movie details
2. Click "Ignore Movie"
3. Movie will be hidden from results

#### View Ignored Movies

```bash
# Via API
curl http://localhost:8080/api/ignored-movies
```

#### Remove from Ignored List

Currently requires database access or API extension.

### Database Maintenance

#### View Statistics

```bash
# Get database statistics
curl http://localhost:8080/api/stats
```

#### Manual Database Operations

```bash
# Access SQLite database
sqlite3 data/cdon_movies.db

# Common maintenance queries
.schema movies
SELECT COUNT(*) FROM movies;
SELECT COUNT(*) FROM price_history;
```

## Advanced Features

### Custom Price Monitoring

#### Multiple Target Prices

While the system supports one target price per movie, you can:

1. Monitor multiple movies with different targets
2. Use alerts to track price movements
3. Manually adjust targets based on market conditions

#### Price Trend Analysis

- View price history charts in movie details
- Track seasonal price patterns
- Identify optimal purchase timing

### Bulk Operations

#### Export Data

```bash
# Export watchlist
curl http://localhost:8080/api/watchlist > watchlist.json

# Export all movies
curl http://localhost:8080/api/movies > all_movies.json
```

#### Import Data

```bash
# Import watchlist (requires custom script)
python scripts/import_watchlist.py watchlist.json
```

### API Integration

#### Programmatic Access

```python
import requests

# Get dashboard stats
response = requests.get('http://localhost:8080/api/stats')
stats = response.json()

# Search movies
response = requests.get('http://localhost:8080/api/search?q=Inception')
movies = response.json()

# Add to watchlist
data = {'product_id': 'MOVIE_ID', 'target_price': 19.99}
response = requests.post('http://localhost:8080/api/watchlist', json=data)
```

#### Third-party Integrations

- **Home Automation**: Trigger smart home actions on price drops
- **Notification Services**: Custom notification handlers
- **Data Analysis**: Export data for external analysis
- **Backup Systems**: Automated data synchronization

## Monitoring and Maintenance

### Service Health Checks

#### Container Health

```bash
# Check container status
podman-compose ps

# View service logs
podman-compose logs -f web
podman-compose logs -f monitor
```

#### Application Health

```bash
# API health check
curl http://localhost:8080/api/stats

# Database connectivity
curl http://localhost:8080/api/movies?limit=1
```

### Performance Monitoring

#### Response Times

Monitor API response times:

```bash
# Time API calls
time curl http://localhost:8080/api/stats
time curl http://localhost:8080/api/movies
```

#### Resource Usage

```bash
# Container resource usage
podman stats

# Database size
ls -lh data/cdon_movies.db
```

### Log Analysis

#### Application Logs

```bash
# View recent logs
podman-compose logs --tail=100 web

# Follow logs in real-time
podman-compose logs -f monitor
```

#### Error Detection

```bash
# Search for errors
podman-compose logs | grep -i error

# Check for scraping failures
podman-compose logs crawler | grep -i fail
```

## Troubleshooting Common Issues

### Web Interface Issues

#### Dashboard Not Loading

```bash
# Check web service status
podman-compose ps web

# Restart web service
podman-compose restart web

# Check web service logs
podman-compose logs web
```

#### Search Not Working

```bash
# Test API directly
curl "http://localhost:8080/api/search?q=test"

# Check database connectivity
curl http://localhost:8080/api/stats
```

### Price Monitoring Issues

#### Monitor Not Running

```bash
# Check monitor status
podman-compose ps monitor

# Start monitor
podman-compose up -d monitor

# Check monitor logs
podman-compose logs monitor
```

#### Missing Price Updates

```bash
# Check last update times
curl http://localhost:8080/api/stats

# Force manual price check
podman-compose run --rm crawler
```

### Data Issues

#### Missing Movies

```bash
# Check total movie count
curl http://localhost:8080/api/stats

# Run new crawl
podman-compose run --rm crawler
```

#### Incorrect Prices

```bash
# Check specific movie
curl "http://localhost:8080/api/search?q=MOVIE_TITLE"

# Manual price verification
# Visit CDON website directly
```

## Best Practices

### Price Monitoring Strategy

1. **Set Realistic Targets**: Base targets on historical data
2. **Monitor Regularly**: Check dashboard daily for alerts
3. **Track Trends**: Use price history for buying decisions
4. **Diversify Watchlist**: Don't focus on single movies

### System Maintenance

1. **Regular Backups**: Use automated backup scripts
2. **Monitor Disk Space**: Database grows over time
3. **Update Regularly**: Keep dependencies current
4. **Log Rotation**: Archive old logs periodically

### Performance Optimization

1. **Database Vacuum**: Regular maintenance for performance
2. **Index Optimization**: Monitor query performance
3. **Cache Management**: Clear caches when needed
4. **Resource Limits**: Set appropriate container limits

## Next Steps

- Configure notifications for price alerts
- Set up automated backups
- Explore API integrations
- Review [API Reference](04_api_reference.md) for advanced usage
- Check [Configuration Guide](06_configuration.md) for customization options
