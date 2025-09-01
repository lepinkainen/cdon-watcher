# CDON Watcher - Project Overview

## What is CDON Watcher?

CDON Watcher is a comprehensive price tracking system specifically designed for Blu-ray and 4K Blu-ray movies available on CDON.fi (Finland's largest online retailer). The system combines web scraping technology with a modern web dashboard to help users track movie prices and get notified about price drops.

## Key Features

### 🎬 **Movie Price Tracking**

- Automated monitoring of Blu-ray and 4K Blu-ray prices
- Historical price tracking with trend analysis
- Real-time price change detection

### 🕷️ **Advanced Web Scraping**

- **Hybrid scraping architecture** combining Playwright and BeautifulSoup
- JavaScript-aware scraping for dynamic content
- Anti-bot protection measures
- **Multi-speed scanning modes**: Fast, moderate, and slow scanning
- Rate limiting and stealth techniques

### 💾 **Robust Data Management**

- SQLite database with SQLModel ORM
- Async database operations for performance
- Type-safe data models with proper relationships
- Data integrity and consistency

### 🌐 **Web Dashboard**

- FastAPI-based web interface
- Real-time statistics and analytics
- Interactive movie search and filtering
- RESTful API for external integrations

### 📧 **Notification System**

- Email notifications for price drops
- Discord webhook integration
- Configurable alert thresholds
- Target price monitoring

### 🐳 **Containerized Deployment**

- Docker/Podman support for easy deployment
- Development and production configurations
- Multi-service architecture with orchestration

## Architecture Overview

### Hybrid Scraping Architecture

CDON Watcher uses a sophisticated **hybrid scraping approach** that combines the best of both worlds:

#### **Listing Crawler (Playwright)**

- Handles JavaScript-heavy category pages
- Extracts product URLs from listing pages
- Manages pagination and category navigation
- Stealth browser configuration for anti-bot protection

#### **Product Parser (BeautifulSoup)**

- Fast, lightweight parsing of individual product pages
- Extracts detailed product information (title, price, format)
- Optimized for performance with minimal overhead
- Pure Python implementation for speed

#### **Orchestrator (CDON Scraper)**

- Coordinates the hybrid workflow
- Manages async database operations
- Handles error recovery and retry logic
- Ensures data consistency across operations

### Service Architecture

The system is built as a **multi-service architecture**:

#### **Web Service**

- FastAPI application serving the dashboard
- RESTful API endpoints
- Jinja2 templating for server-side rendering
- Static file serving for assets

#### **Monitor Service**

- Background price monitoring
- Scheduled price checks (configurable intervals)
- Alert generation and notification dispatch
- Async database operations

#### **Crawler Service**

- **Environment-aware execution**: Runs automatically in production, on-demand in development
- Initial database population and incremental updates
- Multi-speed scanning modes (fast/moderate/slow) for different use cases
- Respectful crawling with configurable delays

### Database Design

The system uses **SQLModel** (SQLAlchemy + Pydantic) for type-safe database operations:

#### **Core Models**

- **Movie**: Main entity with product information
- **PriceHistory**: Time-series price data
- **Watchlist**: User-defined price targets
- **PriceAlert**: Notification history
- **IgnoredMovie**: Filtered content management

#### **Relationships**

- Movies have multiple price history entries
- Watchlist items reference movies
- Price alerts link to movies and price changes
- Proper foreign key constraints and indexing

## Technology Stack

### Backend

- **Python 3.11+**: Modern Python with type hints
- **FastAPI**: High-performance async web framework
- **SQLModel**: Type-safe SQLAlchemy wrapper
- **aiosqlite**: Async SQLite database driver

### Scraping

- **Playwright**: Browser automation for dynamic content
- **BeautifulSoup**: HTML parsing and data extraction
- **requests**: HTTP client with connection pooling

### Web Interface

- **Jinja2**: Server-side templating
- **Vanilla JavaScript**: Client-side interactivity
- **CSS**: Responsive styling

### Development & Quality

- **uv**: Fast Python package manager
- **pytest**: Comprehensive testing framework
- **ruff**: Fast Python linter
- **mypy**: Static type checking

### Deployment

- **Docker/Podman**: Containerization
- **docker-compose**: Multi-service orchestration
- **nginx**: Production web server

## Performance Characteristics

### Scraping Performance

- **Hybrid approach**: ~10x faster than pure Playwright
- **Async operations**: Non-blocking I/O for concurrent requests
- **Smart caching**: Avoids redundant network requests
- **Rate limiting**: Respects website policies

### Database Performance

- **Async operations**: Non-blocking database access
- **Connection pooling**: Efficient resource utilization
- **Optimized queries**: Proper indexing and query planning
- **Type safety**: Compile-time query validation

### Web Performance

- **FastAPI**: High-performance async framework
- **Template caching**: Pre-compiled Jinja2 templates
- **Static file optimization**: Efficient asset serving
- **API optimization**: Minimal serialization overhead

## Security Considerations

### Scraping Ethics

- **Rate limiting**: Respects website capacity
- **Realistic headers**: Mimics legitimate browser traffic
- **Stealth techniques**: Avoids detection patterns
- **Error handling**: Graceful failure recovery

### Data Protection

- **Local storage**: SQLite database remains local
- **No credentials**: Container runs as non-root user
- **Environment isolation**: Configuration via environment variables
- **Access control**: Local network access only

## Development Philosophy

### Code Quality

- **Type safety**: Full mypy coverage with strict settings
- **Testing strategy**: Unit tests for logic, integration tests for workflows
- **Code formatting**: Consistent style with ruff
- **Documentation**: Comprehensive inline and external docs

### Maintainability

- **Modular design**: Clear separation of concerns
- **Dependency management**: Modern Python packaging with uv
- **Configuration management**: Environment-based configuration
- **Error handling**: Comprehensive error recovery

### User Experience

- **Intuitive interface**: Clean, responsive web dashboard
- **Comprehensive API**: RESTful endpoints for integrations
- **Flexible deployment**: Multiple deployment options
- **Clear documentation**: Step-by-step guides and examples
