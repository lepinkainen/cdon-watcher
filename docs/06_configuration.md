# Configuration Guide

This document provides comprehensive documentation of all configuration options available in CDON Watcher, including environment variables, configuration files, and runtime settings.

## Configuration Overview

CDON Watcher uses **environment variables** as the primary configuration mechanism. Configuration is loaded from:

1. **Environment variables** (highest priority)
2. **`.env` file** in the project root
3. **Default values** (lowest priority)

## Environment Variables

### Database Configuration

#### `DB_PATH`

- **Description**: Path to the SQLite database file
- **Default**: `./data/cdon_movies.db`
- **Example**: `/app/data/cdon_movies.db`
- **Notes**: Directory must be writable by the application

#### `POSTER_DIR`

- **Description**: Directory for storing movie poster images
- **Default**: `./data/posters`
- **Example**: `/app/data/posters`
- **Notes**: Used by TMDB integration for poster caching

### Web Server Configuration

#### `API_HOST`

- **Description**: Host address for the web server
- **Default**: `127.0.0.1` (localhost only)
- **Example**: `0.0.0.0` (all interfaces)
- **Notes**: Use `0.0.0.0` for container deployments

#### `API_PORT`

- **Description**: Port number for the web server
- **Default**: `8080`
- **Example**: `3000`
- **Notes**: Must be available and not in use by other services

#### `API_DEBUG`

- **Description**: Enable debug mode for development
- **Default**: `false`
- **Example**: `true`
- **Notes**: Enables detailed error messages and auto-reload

### Scraping Configuration

#### `CHECK_INTERVAL_HOURS`

- **Description**: Hours between price monitoring checks
- **Default**: `6`
- **Example**: `2`
- **Notes**: Lower values increase monitoring frequency but may trigger rate limits

#### `MAX_PAGES_PER_CATEGORY`

- **Description**: Maximum pages to crawl per category during initial crawl
- **Default**: `10`
- **Example**: `20`
- **Notes**: Higher values discover more movies but take longer

#### `REQUEST_TIMEOUT`

- **Description**: Timeout in seconds for HTTP requests
- **Default**: `30`
- **Example**: `60`
- **Notes**: Increase for slow network connections

#### `MAX_RETRIES`

- **Description**: Maximum retry attempts for failed requests
- **Default**: `3`
- **Example**: `5`
- **Notes**: Helps with temporary network issues

### Notification Configuration

#### Email Notifications

##### `EMAIL_ENABLED`

- **Description**: Enable email notifications
- **Default**: `false`
- **Example**: `true`
- **Notes**: Must be `true` to send email notifications

##### `EMAIL_FROM`

- **Description**: Sender email address
- **Default**: (empty)
- **Example**: `your-email@gmail.com`
- **Notes**: Must be a valid email address

##### `EMAIL_TO`

- **Description**: Recipient email address
- **Default**: (empty)
- **Example**: `alerts@yourdomain.com`
- **Notes**: Where price alerts are sent

##### `EMAIL_PASSWORD`

- **Description**: Email account password or app password
- **Default**: (empty)
- **Example**: `your-app-password`
- **Notes**: Use app passwords for Gmail, not account password

##### `SMTP_SERVER`

- **Description**: SMTP server hostname
- **Default**: `smtp.gmail.com`
- **Example**: `smtp.outlook.com`
- **Notes**: Common providers: Gmail, Outlook, Yahoo

##### `SMTP_PORT`

- **Description**: SMTP server port
- **Default**: `587` (TLS)
- **Example**: `465` (SSL)
- **Notes**: 587 for TLS, 465 for SSL, 25 for unencrypted

#### Discord Notifications

##### `DISCORD_WEBHOOK`

- **Description**: Discord webhook URL for notifications
- **Default**: (empty)
- **Example**: `https://discord.com/api/webhooks/123456789/abcdef...`
- **Notes**: Create webhook in Discord server settings

### External Service Integration

#### TMDB Integration

##### `TMDB_API_KEY`

- **Description**: The Movie Database API key
- **Default**: (empty)
- **Example**: `your-tmdb-api-key`
- **Notes**: Get free API key from [TMDB](https://www.themoviedb.org/settings/api)

### Development and Debugging

#### `ENABLE_QUERY_LOGGING`

- **Description**: Log all database queries
- **Default**: `false`
- **Example**: `true`
- **Notes**: Useful for debugging but impacts performance

#### `LOG_LEVEL`

- **Description**: Logging verbosity level
- **Default**: `INFO`
- **Example**: `DEBUG`
- **Notes**: Options: DEBUG, INFO, WARNING, ERROR, CRITICAL

## Configuration File Format

### `.env` File Structure

Create a `.env` file in the project root:

```env
# Database Configuration
DB_PATH=./data/cdon_movies.db
POSTER_DIR=./data/posters

# Web Server Configuration
API_HOST=127.0.0.1
API_PORT=8080
API_DEBUG=false

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

### Environment-Specific Configurations

#### Development Configuration

```env
# Development settings
API_DEBUG=true
API_HOST=127.0.0.1
ENABLE_QUERY_LOGGING=true
LOG_LEVEL=DEBUG
CHECK_INTERVAL_HOURS=1
```

#### Production Configuration

```env
# Production settings
API_DEBUG=false
API_HOST=0.0.0.0
ENABLE_QUERY_LOGGING=false
LOG_LEVEL=WARNING
CHECK_INTERVAL_HOURS=6
EMAIL_ENABLED=true
```

#### Container Configuration

```env
# Container-specific paths
DB_PATH=/app/data/cdon_movies.db
POSTER_DIR=/app/data/posters

# Container networking
API_HOST=0.0.0.0
API_PORT=8080
```

## Configuration Loading

### Loading Priority

Configuration values are loaded in this order (last wins):

1. **Default values** in `config.py`
2. **`.env` file** values
3. **Environment variables** (highest priority)

### Runtime Configuration

```python
from cdon_watcher.config import CONFIG

# Access configuration values
db_path = CONFIG['db_path']
api_port = CONFIG['api_port']
email_enabled = CONFIG['email_enabled']
```

### Dynamic Configuration

Some settings can be changed at runtime:

```python
# Update configuration (requires restart for some settings)
import os
os.environ['CHECK_INTERVAL_HOURS'] = '2'

# Reload configuration
from cdon_watcher.config import load_config
CONFIG = load_config()
```

## Email Configuration Examples

### Gmail Setup

```env
EMAIL_ENABLED=true
EMAIL_FROM=your-email@gmail.com
EMAIL_TO=your-email@gmail.com
EMAIL_PASSWORD=your-app-specific-password
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
```

**Setup Steps:**

1. Enable 2-factor authentication on Gmail
2. Generate app password: [Google Account Settings](https://myaccount.google.com/apppasswords)
3. Use app password, not account password

### Outlook Setup

```env
EMAIL_ENABLED=true
EMAIL_FROM=your-email@outlook.com
EMAIL_TO=your-email@outlook.com
EMAIL_PASSWORD=your-account-password
SMTP_SERVER=smtp-mail.outlook.com
SMTP_PORT=587
```

### Custom SMTP Setup

```env
EMAIL_ENABLED=true
EMAIL_FROM=noreply@yourdomain.com
EMAIL_TO=alerts@yourdomain.com
EMAIL_PASSWORD=your-smtp-password
SMTP_SERVER=mail.yourdomain.com
SMTP_PORT=587
```

## Discord Webhook Setup

### Creating a Discord Webhook

1. **Open Discord** and navigate to your server
2. **Server Settings** → **Integrations** → **Webhooks**
3. **Create Webhook** with desired name and channel
4. **Copy Webhook URL**

### Configuration

```env
DISCORD_WEBHOOK=https://discord.com/api/webhooks/123456789012345678/AbCdEfGhIjKlMnOpQrStUvWxYz
```

### Testing Discord Notifications

```bash
# Test webhook manually
curl -X POST $DISCORD_WEBHOOK \
  -H "Content-Type: application/json" \
  -d '{"content": "Test notification from CDON Watcher"}'
```

## TMDB Integration Setup

### Getting API Key

1. **Create TMDB Account**: [The Movie Database](https://www.themoviedb.org/account/signup)
2. **Request API Key**: Settings → API → Request API Key
3. **Fill Application Form**:
   - Type of use: Personal
   - Application name: CDON Watcher
   - Application URL: Your local URL or repository

### Configuration

```env
TMDB_API_KEY=your-actual-api-key-here
```

### TMDB Features

When configured, CDON Watcher will:

- **Fetch movie metadata** from TMDB
- **Download poster images** for better UI
- **Enhance movie information** with ratings, genres, etc.
- **Cache posters locally** in `POSTER_DIR`

## Advanced Configuration

### Custom Database Location

```env
# Custom database path
DB_PATH=/var/lib/cdon-watcher/movies.db

# Network database (requires SQLite network driver)
DB_PATH=sqlite:////path/to/database.db
```

### High-Frequency Monitoring

```env
# Check prices every hour
CHECK_INTERVAL_HOURS=1

# More aggressive retry settings
MAX_RETRIES=5
REQUEST_TIMEOUT=60
```

### Debug Configuration

```env
# Maximum debugging
API_DEBUG=true
ENABLE_QUERY_LOGGING=true
LOG_LEVEL=DEBUG

# Playwright debugging
PLAYWRIGHT_HEADLESS=false
```

### Production Optimization

```env
# Production settings
API_DEBUG=false
LOG_LEVEL=WARNING
ENABLE_QUERY_LOGGING=false

# Performance tuning
CHECK_INTERVAL_HOURS=4
MAX_PAGES_PER_CATEGORY=15
```

## Configuration Validation

### Required Settings

Some settings are required for specific features:

- **Email**: `EMAIL_FROM`, `EMAIL_TO`, `EMAIL_PASSWORD` (when `EMAIL_ENABLED=true`)
- **Discord**: `DISCORD_WEBHOOK` (when using Discord notifications)
- **TMDB**: `TMDB_API_KEY` (when using TMDB integration)

### Validation Rules

```python
def validate_config(config: dict) -> list[str]:
    """Validate configuration and return list of errors."""
    errors = []

    if config['email_enabled']:
        if not config['email_from']:
            errors.append("EMAIL_FROM is required when EMAIL_ENABLED=true")
        if not config['email_to']:
            errors.append("EMAIL_TO is required when EMAIL_ENABLED=true")
        if not config['email_password']:
            errors.append("EMAIL_PASSWORD is required when EMAIL_ENABLED=true")

    if config['discord_webhook'] and not config['discord_webhook'].startswith('https://discord.com/api/webhooks/'):
        errors.append("DISCORD_WEBHOOK must be a valid Discord webhook URL")

    return errors
```

## Configuration Management

### Version Control

```bash
# Include in version control (with sensitive data removed)
git add .env.example
echo ".env" >> .gitignore

# Never commit sensitive data
git add .env  # ❌ Don't do this
```

### Backup Configuration

```bash
# Backup configuration
cp .env .env.backup

# Restore configuration
cp .env.backup .env
```

### Environment-Specific Files

```bash
# Different configs for different environments
cp .env .env.production
cp .env .env.staging
cp .env .env.development

# Use with docker-compose
docker-compose --env-file .env.production up -d
```

## Troubleshooting Configuration

### Common Issues

#### Configuration Not Loading

```bash
# Check if .env file exists
ls -la .env

# Check file permissions
ls -l .env

# Validate syntax
python -c "import dotenv; dotenv.load_dotenv(); print('OK')"
```

#### Environment Variables Not Working

```bash
# Check current environment
env | grep -E "(DB_PATH|API_PORT|EMAIL)"

# Set environment variable
export API_PORT=3000

# Check if variable is set
echo $API_PORT
```

#### Database Connection Issues

```bash
# Check database path
ls -la $DB_PATH

# Check permissions
ls -ld $(dirname $DB_PATH)

# Test database connection
python -c "import sqlite3; sqlite3.connect('$DB_PATH').close(); print('OK')"
```

#### Email Not Working

```bash
# Test SMTP connection
telnet $SMTP_SERVER $SMTP_PORT

# Check credentials
# Try sending test email manually
```

#### Webhook Not Working

```bash
# Test Discord webhook
curl -X POST $DISCORD_WEBHOOK \
  -H "Content-Type: application/json" \
  -d '{"content": "Test message"}'

# Check webhook URL format
echo $DISCORD_WEBHOOK | grep -E "https://discord.com/api/webhooks/[0-9]+/[a-zA-Z0-9_-]+"
```

### Debug Commands

```bash
# Show current configuration
python -c "from cdon_watcher.config import CONFIG; import json; print(json.dumps(CONFIG, indent=2))"

# Test configuration loading
python -c "from cdon_watcher.config import load_config; print(load_config())"

# Validate configuration
python -c "
from cdon_watcher.config import CONFIG
errors = []
if CONFIG['email_enabled'] and not CONFIG['email_from']:
    errors.append('Missing EMAIL_FROM')
print('Configuration errors:', errors)
"
```

## Security Considerations

### Sensitive Data

- **Never commit** `.env` files with real credentials
- **Use environment variables** for sensitive data in production
- **Rotate credentials** regularly
- **Use app passwords** instead of account passwords

### File Permissions

```bash
# Secure configuration file
chmod 600 .env

# Secure data directory
chmod 700 data/
chmod 600 data/cdon_movies.db
```

### Network Security

- **Use HTTPS** in production
- **Restrict API access** with firewall rules
- **Monitor API usage** for abuse
- **Rate limit** API endpoints if needed

## Best Practices

### Configuration Management

1. **Use `.env.example`** as template
2. **Document all settings** in comments
3. **Validate configuration** on startup
4. **Use environment variables** for secrets

### Security

1. **Separate credentials** from code
2. **Use strong passwords** and app passwords
3. **Restrict file permissions**
4. **Monitor configuration access**

### Maintenance

1. **Regular backup** of configuration
2. **Version control** of configuration templates
3. **Document changes** in configuration
4. **Test configuration** changes

### Monitoring

1. **Log configuration** loading
2. **Monitor configuration** changes
3. **Alert on configuration** errors
4. **Audit configuration** access
