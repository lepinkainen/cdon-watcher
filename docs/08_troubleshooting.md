# Troubleshooting Guide

This guide provides solutions to common issues encountered when using CDON Watcher, including setup problems, runtime errors, and performance issues.

## Quick Diagnosis

### System Health Check

Run this command to check overall system health:

```bash
# Check all services
podman-compose ps

# Check logs for errors
podman-compose logs --tail=50

# Test API connectivity
curl -s http://localhost:8080/api/stats | jq .

# Check database
sqlite3 data/cdon_movies.db "SELECT COUNT(*) FROM movies;"

# Test scraping
uv run python -c "from cdon_watcher.cdon_scraper import CDONScraper; print('Import OK')"
```

## Installation Issues

### Python Version Problems

#### Issue: "Python 3.11+ required"

**Symptoms:**

```
ModuleNotFoundError: No module named 'typing_extensions'
ImportError: cannot import name 'Literal' from 'typing'
```

**Solutions:**

1. **Check Python version:**

   ```bash
   python --version
   # Should show Python 3.11.x or higher
   ```

2. **Update Python:**

   ```bash
   # macOS with Homebrew
   brew update
   brew upgrade python

   # Ubuntu/Debian
   sudo apt update
   sudo apt install python3.11 python3.11-venv

   # Or use pyenv
   pyenv install 3.11.0
   pyenv global 3.11.0
   ```

3. **Use correct Python binary:**

   ```bash
   # Instead of python, use:
   python3.11 -m pip install -r requirements.txt
   ```

#### Issue: Virtual environment not working

**Symptoms:**

```
bash: source: command not found
```

**Solutions:**

```bash
# Create virtual environment correctly
python3 -m venv venv

# Activate on different shells
# bash/zsh
source venv/bin/activate

# fish shell
source venv/bin/activate.fish

# Windows
venv\Scripts\activate

# Check activation
which python  # Should show venv path
```

### Dependency Installation Issues

#### Issue: uv installation fails

**Symptoms:**

```
curl: command not found
```

**Solutions:**

```bash
# Install curl first
# Ubuntu/Debian
sudo apt install curl

# macOS
# curl is pre-installed

# Alternative uv installation
pip install uv

# Or use pip-tools
pip install pip-tools
```

#### Issue: Package installation fails

**Symptoms:**

```
ERROR: Could not build wheels for <package>
```

**Solutions:**

```bash
# Install build dependencies
sudo apt install build-essential python3-dev

# Or use pre-compiled wheels
pip install --only-binary=all <package>

# Clear pip cache
pip cache purge
```

#### Issue: Playwright browser installation fails

**Symptoms:**

```
Browser installation failed
```

**Solutions:**

```bash
# Manual browser installation
uv run playwright install chromium

# Force reinstall
uv run playwright install --force chromium

# Check system dependencies
# Ubuntu/Debian
sudo apt install libnss3 libatk-bridge2.0-0 libdrm2 libxkbcommon0 libgtk-3-0 libgbm1

# macOS
# Usually works out of the box
```

### Container Issues

#### Issue: Podman/Docker not found

**Symptoms:**

```
podman: command not found
```

**Solutions:**

```bash
# Install Podman (macOS)
brew install podman podman-compose

# Install Docker (Linux)
curl -fsSL https://get.docker.com | sh
sudo systemctl start docker
sudo systemctl enable docker

# Add user to docker group
sudo usermod -aG docker $USER
# Logout and login again
```

#### Issue: Container build fails

**Symptoms:**

```
ERROR: failed to solve: process "/bin/sh -c apt-get update" did not complete successfully
```

**Solutions:**

```bash
# Clear Docker cache
docker system prune -a

# Rebuild without cache
docker-compose build --no-cache

# Check disk space
df -h

# Fix DNS issues in containers
echo 'nameserver 8.8.8.8' | sudo tee /etc/resolv.conf
```

## Runtime Issues

### Web Interface Problems

#### Issue: Dashboard not loading

**Symptoms:**

- Browser shows connection refused
- 502 Bad Gateway error
- Blank page

**Solutions:**

1. **Check service status:**

   ```bash
   podman-compose ps
   # Should show web service as "Up"
   ```

2. **Check service logs:**

   ```bash
   podman-compose logs web
   # Look for startup errors
   ```

3. **Restart web service:**

   ```bash
   podman-compose restart web
   ```

4. **Check port availability:**

   ```bash
   netstat -tlnp | grep 8080
   # Should show service listening
   ```

5. **Test API directly:**

   ```bash
   curl http://localhost:8080/api/stats
   ```

#### Issue: API returns 500 errors

**Symptoms:**

- API endpoints return server errors
- Database connection issues

**Solutions:**

```bash
# Check database file
ls -la data/cdon_movies.db

# Test database connection
python -c "
import sqlite3
conn = sqlite3.connect('data/cdon_movies.db')
conn.execute('SELECT 1').fetchone()
print('Database OK')
"

# Check application logs
podman-compose logs web | tail -20

# Restart services
podman-compose down
podman-compose up -d
```

### Scraping Issues

#### Issue: Price scraping fails

**Symptoms:**

- No prices in database
- Scraping errors in logs
- Empty search results

**Solutions:**

1. **Check network connectivity:**

   ```bash
   curl -I https://cdon.fi
   # Should return 200 OK
   ```

2. **Test scraping manually:**

   ```bash
   uv run python -c "
   from cdon_watcher.product_parser import ProductParser
   parser = ProductParser()
   # Test with known product URL
   "
   ```

3. **Check for website changes:**
   - CDON may have updated their HTML structure
   - Check browser developer tools for page changes

4. **Update scraping logic:**

   ```bash
   # Rebuild containers with latest code
   podman-compose build --no-cache
   podman-compose up -d
   ```

#### Issue: Playwright browser crashes

**Symptoms:**

- Browser automation fails
- Headless mode issues
- Memory errors

**Solutions:**

```bash
# Run in non-headless mode for debugging
export PLAYWRIGHT_HEADLESS=false

# Increase container memory
podman-compose up -d --scale crawler=1

# Check system resources
free -h  # Linux
top      # macOS

# Update Playwright
uv run playwright install --force
```

### Database Issues

#### Issue: Database locked errors

**Symptoms:**

```
sqlite3.OperationalError: database is locked
```

**Solutions:**

1. **Stop all services:**

   ```bash
   podman-compose down
   ```

2. **Remove lock file:**

   ```bash
   rm -f data/cdon_movies.db-journal
   ```

3. **Check database integrity:**

   ```bash
   sqlite3 data/cdon_movies.db "PRAGMA integrity_check;"
   ```

4. **Restart services:**

   ```bash
   podman-compose up -d
   ```

#### Issue: Database corruption

**Symptoms:**

- Random crashes
- Data inconsistency
- Integrity check fails

**Solutions:**

```bash
# Create backup
cp data/cdon_movies.db data/cdon_movies.db.backup

# Attempt repair
sqlite3 data/cdon_movies.db ".recover" > recovered.sql
sqlite3 recovered.db < recovered.sql

# If repair fails, restore from backup
# Check backup scripts in scripts/ directory
```

#### Issue: Database file permissions

**Symptoms:**

```
sqlite3.OperationalError: unable to open database file
```

**Solutions:**

```bash
# Fix permissions
chmod 644 data/cdon_movies.db
chmod 755 data/

# Check ownership
ls -la data/cdon_movies.db

# Fix ownership if needed
sudo chown $USER:$USER data/cdon_movies.db
```

### Notification Issues

#### Issue: Discord webhooks failing

**Symptoms:**

- Discord notifications not sent
- Webhook errors in logs

**Solutions:**

1. **Verify webhook URL:**

   ```bash
   curl -X POST $DISCORD_WEBHOOK \
     -H "Content-Type: application/json" \
     -d '{"content": "Test message"}'
   ```

2. **Check webhook permissions:**
   - Ensure bot has message permissions
   - Verify webhook URL is correct

3. **Test webhook format:**

   ```json
   {
     "content": "Price alert: Movie dropped to €19.99",
     "embeds": [
       {
         "title": "Price Alert",
         "description": "Movie price has changed",
         "color": 16711680
       }
     ]
   }
   ```

## Performance Issues

### High CPU Usage

**Symptoms:**

- Container using excessive CPU
- System slowdown

**Solutions:**

1. **Check monitoring frequency:**

   ```bash
   # Reduce check interval
   export CHECK_INTERVAL_HOURS=12
   ```

2. **Limit concurrent operations:**

   ```bash
   # Reduce crawler instances
   podman-compose up -d --scale crawler=1
   ```

3. **Monitor resource usage:**

   ```bash
   podman stats
   ```

### High Memory Usage

**Symptoms:**

- Out of memory errors
- Container restarts

**Solutions:**

1. **Increase container memory:**

   ```yaml
   # docker-compose.yml
   services:
     web:
       deploy:
         resources:
           limits:
             memory: 1G
   ```

2. **Optimize database queries:**

   ```bash
   # Add database indexes
   sqlite3 data/cdon_movies.db "CREATE INDEX IF NOT EXISTS idx_price_history_date ON price_history(checked_at);"
   ```

3. **Clear old data:**

   ```bash
   # Vacuum database
   sqlite3 data/cdon_movies.db "VACUUM;"
   ```

### Slow Response Times

**Symptoms:**

- API calls taking too long
- Web interface lag

**Solutions:**

1. **Check database performance:**

   ```bash
   sqlite3 data/cdon_movies.db "EXPLAIN QUERY PLAN SELECT * FROM movies LIMIT 10;"
   ```

2. **Optimize queries:**

   ```python
   # Use selectinload for relationships
   stmt = select(Movie).options(selectinload(Movie.price_history))
   ```

3. **Add caching:**

   ```python
   from functools import lru_cache

   @lru_cache(maxsize=100)
   def get_movie_stats():
       # Cache expensive operations
   ```

## Network Issues

### Connection Timeouts

**Symptoms:**

- Scraping fails with timeout errors
- Network-related exceptions

**Solutions:**

1. **Increase timeout values:**

   ```bash
   export REQUEST_TIMEOUT=60
   export MAX_RETRIES=5
   ```

2. **Check network connectivity:**

   ```bash
   ping cdon.fi
   traceroute cdon.fi
   ```

3. **Use different DNS:**

   ```bash
   # Add to /etc/resolv.conf
   nameserver 8.8.8.8
   nameserver 1.1.1.1
   ```

### SSL Certificate Issues

**Symptoms:**

```
ssl.SSLCertVerificationError
```

**Solutions:**

1. **Update CA certificates:**

   ```bash
   # Ubuntu/Debian
   sudo apt install ca-certificates
   sudo update-ca-certificates

   # macOS
   # Usually handled by system
   ```

2. **Disable SSL verification (temporary):**

   ```python
   import ssl
   ssl._create_default_https_context = ssl._create_unverified_context
   ```

3. **Check system time:**

   ```bash
   date
   # Time should be correct for certificate validation
   ```

## Configuration Issues

### Environment Variables Not Loading

**Symptoms:**

- Configuration changes not taking effect
- Default values being used

**Solutions:**

1. **Check `.env` file location:**

   ```bash
   ls -la .env
   pwd  # Should be project root
   ```

2. **Verify file format:**

   ```bash
   cat .env | grep -v '^#' | grep -v '^$'
   # Should show KEY=VALUE pairs
   ```

3. **Check file permissions:**

   ```bash
   ls -l .env
   # Should be readable by application
   ```

4. **Restart services:**

   ```bash
   podman-compose down
   podman-compose up -d
   ```

### Invalid Configuration Values

**Symptoms:**

- Application fails to start
- Configuration validation errors

**Solutions:**

1. **Validate configuration:**

   ```python
   python -c "
   from cdon_watcher.config import CONFIG
   print('Configuration loaded successfully')
   for key, value in CONFIG.items():
       print(f'{key}: {value}')
   "
   ```

2. **Check required fields:**

   ```bash
   # For Discord notifications
   if [ -z "$DISCORD_WEBHOOK" ]; then echo "DISCORD_WEBHOOK not set"; fi
   ```

3. **Use configuration validation:**

   ```python
   def validate_config():
       required = ['DB_PATH', 'API_HOST', 'API_PORT']
       for key in required:
           if not CONFIG.get(key):
               raise ValueError(f"Required config {key} is missing")
   ```

## Log Analysis

### Reading Application Logs

```bash
# View recent logs
podman-compose logs --tail=100 web

# Follow logs in real-time
podman-compose logs -f monitor

# Search for specific errors
podman-compose logs | grep -i error

# Filter by time
podman-compose logs --since "1h" web
```

### Common Log Patterns

#### Scraping Errors

```
ERROR - Failed to scrape product MOVIE_123: TimeoutError
ERROR - Page load failed: net::ERR_NETWORK_CHANGED
```

**Solutions:**

- Increase timeout values
- Check network stability
- Implement retry logic

#### Database Errors

```
ERROR - Database connection failed: (sqlite3.OperationalError) database is locked
ERROR - Integrity error: UNIQUE constraint failed
```

**Solutions:**

- Check database file permissions
- Implement connection pooling
- Add transaction handling

#### API Errors

```
ERROR - 500 Internal Server Error: asyncpg.exceptions.ConnectionDoesNotExistError
ERROR - Validation error: product_id must be string
```

**Solutions:**

- Check database connectivity
- Validate input parameters
- Add proper error handling

## Advanced Troubleshooting

### Debug Mode

Enable debug mode for detailed logging:

```bash
# Set debug environment
export API_DEBUG=true
export LOG_LEVEL=DEBUG

# Restart services
podman-compose down
podman-compose up -d
```

### Profiling Performance

```python
# Profile application
python -m cProfile -s cumulative -o profile.stats your_script.py

# Analyze profile
python -c "
import pstats
p = pstats.Stats('profile.stats')
p.sort_stats('cumulative').print_stats(20)
"
```

### Memory Leak Detection

```python
# Check for memory leaks
import tracemalloc
tracemalloc.start()

# Your code here

current, peak = tracemalloc.get_traced_memory()
print(f"Current memory usage: {current / 1024 / 1024:.1f} MB")
print(f"Peak memory usage: {peak / 1024 / 1024:.1f} MB")
```

### Network Debugging

```bash
# Monitor network traffic
tcpdump -i any port 8080

# Check DNS resolution
nslookup cdon.fi

# Test with different user agents
curl -H "User-Agent: Mozilla/5.0..." https://cdon.fi
```

## Getting Help

### Information to Provide

When reporting issues, include:

1. **System information:**

   ```bash
   uname -a
   python --version
   podman --version
   ```

2. **Configuration (sanitized):**

   ```bash
   env | grep -E "(API_|DB_|DISCORD_)" | head -10
   ```

3. **Error logs:**

   ```bash
   podman-compose logs --tail=50
   ```

4. **Steps to reproduce:**
   - Exact commands used
   - Expected vs actual behavior

### Support Channels

1. **GitHub Issues:** For bugs and feature requests
2. **GitHub Discussions:** For questions and help
3. **Documentation:** Check this troubleshooting guide
4. **Community:** Check existing issues for similar problems

### Emergency Procedures

#### Data Loss Recovery

```bash
# Stop all services
podman-compose down

# Restore from backup
cp backup/cdon_movies.db.backup data/cdon_movies.db

# Verify database integrity
sqlite3 data/cdon_movies.db "PRAGMA integrity_check;"

# Restart services
podman-compose up -d
```

#### Service Recovery

```bash
# Force restart all services
podman-compose down
podman-compose up -d --force-recreate

# Check service health
podman-compose ps
podman-compose logs --tail=20
```

## Prevention

### Regular Maintenance

1. **Monitor logs daily**
2. **Check disk space weekly**
3. **Update dependencies monthly**
4. **Backup data regularly**

### Monitoring Setup

```bash
# Set up log rotation
# Add to docker-compose.yml
services:
  web:
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

### Proactive Checks

```bash
# Health check script
#!/bin/bash
# Check service status
if ! podman-compose ps | grep -q "Up"; then
    echo "Services are down, restarting..."
    podman-compose restart
fi

# Check database size
DB_SIZE=$(stat -f%z data/cdon_movies.db 2>/dev/null || stat -c%s data/cdon_movies.db)
if [ $DB_SIZE -gt 1000000000 ]; then  # 1GB
    echo "Database is large, consider vacuuming"
fi

# Check disk space
DISK_USAGE=$(df / | tail -1 | awk '{print $5}' | sed 's/%//')
if [ $DISK_USAGE -gt 90 ]; then
    echo "Low disk space warning"
fi
```

This comprehensive troubleshooting guide should help resolve most common issues with CDON Watcher. If you encounter problems not covered here, please check the GitHub repository for similar issues or create a new issue with detailed information.
