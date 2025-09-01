# Development Guide

This document provides comprehensive guidelines for developing CDON Watcher, including coding standards, testing practices, contribution workflows, and development environment setup.

## Development Environment Setup

### Prerequisites

- **Python 3.11+**: Required version with type hints support
- **uv**: Fast Python package manager (recommended)
- **Git**: Version control system
- **VS Code**: Recommended IDE with extensions

### Quick Setup

```bash
# 1. Clone repository
git clone https://github.com/lepinkainen/cdon-watcher.git
cd cdon-watcher

# 2. Install dependencies with uv
uv sync --extra test --extra dev

# 3. Install Playwright browsers
uv run playwright install chromium

# 4. Copy configuration
cp .env.example .env

# 5. Run tests to verify setup
uv run pytest tests/unit/
```

### IDE Configuration

#### VS Code Extensions

Install these recommended extensions:

```json
{
  "recommendations": [
    "ms-python.python",
    "ms-python.pylance",
    "ms-python.ruff",
    "ms-playwright.playwright",
    "ms-vscode.vscode-json",
    "redhat.vscode-yaml",
    "ms-vscode-remote.remote-containers"
  ]
}
```

#### VS Code Settings

```json
{
  "python.defaultInterpreterPath": "./.venv/bin/python",
  "python.formatting.provider": "none",
  "editor.codeActionsOnSave": {
    "source.fixAll.ruff": "explicit",
    "source.organizeImports.ruff": "explicit"
  },
  "editor.formatOnSave": true,
  "ruff.enable": true,
  "ruff.organizeImports": true,
  "ruff.fixAll": true
}
```

## Code Quality Standards

### Python Style Guide

#### Ruff Configuration

The project uses Ruff for fast Python linting and formatting:

```toml
[tool.ruff]
target-version = "py311"
line-length = 100
extend-exclude = ["__pycache__", ".venv"]

[tool.ruff.lint]
select = ["E", "F", "W", "B", "I", "N", "UP", "C90"]
ignore = ["E501", "B008"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
```

#### Type Checking

Use mypy for static type checking:

```toml
[tool.mypy]
python_version = "3.11"
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
disallow_incomplete_defs = true
check_untyped_defs = true
disallow_untyped_decorators = true
no_implicit_optional = true
warn_redundant_casts = true
warn_unused_ignores = true
warn_no_return = true
warn_unreachable = true
strict_equality = true
```

### Naming Conventions

#### Variables and Functions

```python
# Good
def get_movie_by_id(movie_id: str) -> Movie | None:
    """Get movie by product ID."""

# Bad
def getMovieById(movieId: str) -> Movie | None:  # camelCase
def get_movie(movie_id):  # Missing type hints
```

#### Classes and Types

```python
# Good
class MoviePriceAlert(SQLModel):
    """Alert for movie price changes."""

# Bad
class movie_price_alert:  # snake_case for classes
class MoviePriceAlert:    # No type hints in docstring
```

#### Constants

```python
# Good
DEFAULT_CHECK_INTERVAL = 6
MAX_RETRY_ATTEMPTS = 3

# Bad
defaultCheckInterval = 6  # camelCase
DEFAULT_CHECK_INTERVAL = "6"  # String instead of int
```

### Documentation Standards

#### Docstrings

Use Google-style docstrings:

```python
def scrape_movie_price(product_id: str, url: str) -> float | None:
    """Scrape current price for a movie from CDON.

    Args:
        product_id: Unique CDON product identifier
        url: Product page URL to scrape

    Returns:
        Current price in euros, or None if scraping failed

    Raises:
        ScrapingError: If page cannot be loaded or parsed
        NetworkError: If network request fails

    Example:
        >>> price = scrape_movie_price("MOVIE_123", "https://cdon.fi/movie")
        >>> print(f"Price: {price}€")
        Price: 24.99€
    """
```

#### Comments

```python
# Good: Explain why, not what
movies = []  # Use list for O(1) appends and fast iteration

# Bad: Redundant comment
movies = []  # Create empty list for movies
```

### Error Handling

#### Custom Exceptions

```python
class CDONWatcherError(Exception):
    """Base exception for CDON Watcher."""
    pass

class ScrapingError(CDONWatcherError):
    """Raised when scraping fails."""
    pass

class DatabaseError(CDONWatcherError):
    """Raised when database operations fail."""
    pass
```

#### Error Handling Patterns

```python
# Good: Specific exception handling
try:
    price = await scrape_price(product_id)
except ScrapingError as e:
    logger.error(f"Failed to scrape {product_id}: {e}")
    return None
except Exception as e:
    logger.exception(f"Unexpected error scraping {product_id}")
    raise

# Bad: Bare except
try:
    price = await scrape_price(product_id)
except:
    return None
```

## Testing Practices

### Test Structure

```
tests/
├── unit/           # Unit tests (no external dependencies)
├── integration/    # Integration tests (real network/database)
├── conftest.py     # Shared test fixtures
└── test_*.py       # Test files
```

### Unit Testing

#### Test File Structure

```python
# tests/unit/test_scraper.py
import pytest
from unittest.mock import Mock, AsyncMock

from cdon_watcher.cdon_scraper import CDONScraper
from cdon_watcher.models import Movie

class TestCDONScraper:
    """Test CDON scraper functionality."""

    @pytest.fixture
    def scraper(self):
        """Create scraper instance for testing."""
        return CDONScraper()

    @pytest.mark.asyncio
    async def test_scrape_movie_success(self, scraper):
        """Test successful movie scraping."""
        # Arrange
        product_id = "MOVIE_123"
        expected_price = 24.99

        # Mock dependencies
        scraper.product_parser.scrape_price = AsyncMock(return_value=expected_price)

        # Act
        result = await scraper.scrape_movie(product_id)

        # Assert
        assert result == expected_price
        scraper.product_parser.scrape_price.assert_called_once_with(product_id)

    @pytest.mark.asyncio
    async def test_scrape_movie_failure(self, scraper):
        """Test movie scraping failure."""
        # Arrange
        product_id = "MOVIE_123"
        scraper.product_parser.scrape_price = AsyncMock(side_effect=Exception("Network error"))

        # Act & Assert
        with pytest.raises(Exception, match="Network error"):
            await scraper.scrape_movie(product_id)
```

#### Test Fixtures

```python
# tests/conftest.py
import pytest
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from cdon_watcher.database.connection import init_db
from cdon_watcher.models import SQLModel

@pytest.fixture
async def db_session():
    """Create in-memory database session for testing."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    # Create session
    async_session = sessionmaker(engine, class_=AsyncSession)
    session = async_session()

    try:
        yield session
    finally:
        await session.close()
        await engine.dispose()

@pytest.fixture
def sample_movie():
    """Create sample movie data."""
    return {
        "product_id": "MOVIE_123",
        "title": "Inception",
        "format": "Blu-ray",
        "url": "https://cdon.fi/movie/inception",
        "price": 24.99
    }
```

### Integration Testing

#### Network Testing

```python
# tests/integration/test_scraper_integration.py
import pytest
from unittest.mock import patch

from cdon_watcher.cdon_scraper import CDONScraper

class TestCDONScraperIntegration:
    """Integration tests for CDON scraper."""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_real_scraping(self):
        """Test scraping real CDON pages."""
        scraper = CDONScraper()

        # Test with known product
        product_id = "MOVIE_123"
        price = await scraper.scrape_movie(product_id)

        assert price is not None
        assert isinstance(price, (int, float))
        assert price > 0

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_category_crawling(self):
        """Test crawling movie categories."""
        scraper = CDONScraper()

        movies = await scraper.crawl_category(
            "https://cdon.fi/elokuvat/?facets=property_preset_media_format%3Ablu-ray",
            max_pages=1
        )

        assert isinstance(movies, list)
        assert len(movies) > 0

        # Validate movie structure
        movie = movies[0]
        assert "product_id" in movie
        assert "title" in movie
        assert "price" in movie
```

### Test Execution

#### Running Tests

```bash
# Run all tests
uv run pytest

# Run unit tests only
uv run pytest tests/unit/

# Run integration tests
uv run pytest tests/integration/

# Run with coverage
uv run pytest --cov=cdon_watcher --cov-report=html

# Run specific test
uv run pytest tests/unit/test_scraper.py::TestCDONScraper::test_scrape_movie_success

# Run tests matching pattern
uv run pytest -k "scraper and success"
```

#### Test Configuration

```ini
# pytest.ini
[tool:pytest]
asyncio_mode = auto
testpaths = tests
addopts = --timeout=60
timeout = 60
markers =
    integration: marks tests as integration tests (deselect with '-m "not integration"')
    slow: marks tests as slow (deselect with '-m "not slow"')
```

## Git Workflow

### Branch Naming

```bash
# Feature branches
feature/add-discord-notifications
feature/improve-scraping-performance

# Bug fixes
bugfix/fix-price-parsing-error
bugfix/handle-network-timeouts

# Documentation
docs/update-api-documentation
docs/add-contribution-guide

# Refactoring
refactor/extract-database-layer
refactor/simplify-scraper-logic
```

### Commit Messages

Follow conventional commit format:

```bash
# Good commit messages
feat: add Discord webhook notifications
fix: handle network timeouts in scraper
docs: update API documentation
refactor: extract database operations to repository
test: add integration tests for price monitoring

# Bad commit messages
Fixed bug
Updated code
Changes
```

### Pull Request Process

#### PR Template

```markdown
## Description

Brief description of changes

## Type of Change

- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update
- [ ] Refactoring

## Testing

- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] Manual testing completed

## Checklist

- [ ] Code follows style guidelines
- [ ] Documentation updated
- [ ] Tests added/updated
- [ ] No breaking changes
```

#### Code Review Guidelines

**Reviewers should check:**

- Code follows style guidelines
- Tests are comprehensive
- Documentation is updated
- No security vulnerabilities
- Performance implications considered

**Authors should:**

- Address all review comments
- Keep PRs focused and small
- Test changes thoroughly
- Update documentation

## Code Architecture

### Project Structure

```
src/cdon_watcher/
├── __init__.py          # Package initialization
├── __main__.py          # Module entry point
├── cli.py              # Command-line interface
├── config.py           # Configuration management
├── models.py           # SQLModel database models
├── schemas.py          # Pydantic API schemas
├── cdon_scraper.py     # Main scraper orchestrator
├── listing_crawler.py  # Playwright category crawler
├── product_parser.py   # BeautifulSoup product parser
├── monitoring_service.py # Price monitoring logic
├── notifications.py    # Email/Discord notifications
├── tmdb_service.py     # TMDB integration
├── database/           # Database layer
│   ├── __init__.py
│   ├── connection.py   # Database connection setup
│   └── repository.py   # Data access layer
├── web/               # Web application
│   ├── __init__.py
│   ├── app.py         # FastAPI application setup
│   └── routes.py      # API route definitions
├── static/            # Static web assets
│   ├── css/
│   └── js/
└── templates/         # Jinja2 templates
    └── index.html
```

### Design Patterns

#### Repository Pattern

```python
class DatabaseRepository:
    """Repository for database operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_movie_by_id(self, movie_id: int) -> Movie | None:
        """Get movie by database ID."""
        stmt = select(Movie).where(Movie.id == movie_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_movie(self, movie_data: dict) -> Movie:
        """Create new movie."""
        movie = Movie(**movie_data)
        self.session.add(movie)
        await self.session.commit()
        await self.session.refresh(movie)
        return movie
```

#### Factory Pattern

```python
class NotificationFactory:
    """Factory for creating notification services."""

    @staticmethod
    def create_notification_service(config: dict) -> NotificationService:
        """Create appropriate notification service."""
        if config.get('discord_webhook'):
            return DiscordNotificationService(config['discord_webhook'])
        elif config.get('email_enabled'):
            return EmailNotificationService(config)
        else:
            return NullNotificationService()
```

#### Strategy Pattern

```python
class ScrapingStrategy(ABC):
    """Abstract base class for scraping strategies."""

    @abstractmethod
    async def scrape_price(self, product_id: str) -> float | None:
        """Scrape price for product."""
        pass

class PlaywrightStrategy(ScrapingStrategy):
    """Playwright-based scraping strategy."""

    async def scrape_price(self, product_id: str) -> float | None:
        # Implementation...

class BeautifulSoupStrategy(ScrapingStrategy):
    """BeautifulSoup-based scraping strategy."""

    async def scrape_price(self, product_id: str) -> float | None:
        # Implementation...
```

## Performance Optimization

### Database Optimization

#### Query Optimization

```python
# Good: Use selectinload for relationships
stmt = select(Movie).options(selectinload(Movie.price_history))
result = await session.execute(stmt)

# Bad: N+1 query problem
movies = await session.execute(select(Movie))
for movie in movies:
    price_history = await session.execute(
        select(PriceHistory).where(PriceHistory.movie_id == movie.id)
    )
```

#### Indexing Strategy

```python
# Add indexes for frequently queried columns
class Movie(SQLModel, table=True):
    product_id: str = Field(unique=True, index=True)
    title: str = Field(index=True)
    tmdb_id: int | None = Field(index=True)
```

### Async Best Practices

#### Proper Async Usage

```python
# Good: Use asyncio.gather for concurrent operations
async def update_prices(movie_ids: list[int]):
    tasks = [scrape_price(movie_id) for movie_id in movie_ids]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return results

# Bad: Sequential operations
async def update_prices(movie_ids: list[int]):
    results = []
    for movie_id in movie_ids:
        result = await scrape_price(movie_id)
        results.append(result)
    return results
```

#### Connection Pooling

```python
# Configure connection pool
engine = create_async_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_recycle=3600
)
```

## Security Guidelines

### Input Validation

```python
def validate_product_id(product_id: str) -> bool:
    """Validate CDON product ID format."""
    import re
    pattern = r'^[A-Z0-9_]{1,50}$'
    return bool(re.match(pattern, product_id))

def sanitize_url(url: str) -> str:
    """Sanitize and validate URL."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.scheme not in ['http', 'https']:
        raise ValueError("Invalid URL scheme")
    if 'cdon.fi' not in parsed.netloc:
        raise ValueError("URL must be from cdon.fi")
    return url
```

### Secret Management

```python
# Use environment variables for secrets
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    database_url = os.getenv('DATABASE_URL')
    secret_key = os.getenv('SECRET_KEY')
    api_key = os.getenv('API_KEY')

    @classmethod
    def validate_secrets(cls):
        """Validate that all required secrets are present."""
        required = ['database_url', 'secret_key']
        missing = [key for key in required if not getattr(cls, key)]
        if missing:
            raise ValueError(f"Missing required secrets: {missing}")
```

### SQL Injection Prevention

```python
# Good: Use parameterized queries
stmt = select(Movie).where(Movie.product_id == product_id)
result = await session.execute(stmt)

# Bad: String formatting (vulnerable to SQL injection)
query = f"SELECT * FROM movies WHERE product_id = '{product_id}'"
result = await session.execute(text(query))
```

## Debugging Techniques

### Logging Configuration

```python
import logging
from logging.config import dictConfig

LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        },
        'detailed': {
            'format': '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
        }
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'standard',
            'level': 'INFO'
        },
        'file': {
            'class': 'logging.FileHandler',
            'filename': 'cdon_watcher.log',
            'formatter': 'detailed',
            'level': 'DEBUG'
        }
    },
    'loggers': {
        'cdon_watcher': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG',
            'propagate': False
        }
    }
}

dictConfig(LOGGING_CONFIG)
logger = logging.getLogger('cdon_watcher')
```

### Debug Tools

#### PDB Debugging

```python
# Add breakpoint
import pdb; pdb.set_trace()

# Or use ipdb for better interface
import ipdb; ipdb.set_trace()
```

#### Memory Profiling

```python
from memory_profiler import profile

@profile
def expensive_function():
    # Function to profile
    pass
```

#### Performance Profiling

```python
import cProfile
import pstats

def profile_function(func):
    def wrapper(*args, **kwargs):
        profiler = cProfile.Profile()
        profiler.enable()
        result = func(*args, **kwargs)
        profiler.disable()
        stats = pstats.Stats(profiler).sort_stats('cumulative')
        stats.print_stats(20)  # Top 20 functions
        return result
    return wrapper

@profile_function
def my_function():
    pass
```

## Continuous Integration

### GitHub Actions Workflow

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: [3.11, 3.12]

    steps:
      - uses: actions/checkout@v4
      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v4
        with:
          python-version: ${{ matrix.python-version }}

      - name: Install uv
        run: curl -LsSf https://astral.sh/uv/install.sh | sh

      - name: Install dependencies
        run: uv sync --extra test --extra dev

      - name: Run tests
        run: uv run pytest --cov=cdon_watcher --cov-report=xml

      - name: Upload coverage
        uses: codecov/codecov-action@v3
        with:
          file: ./coverage.xml

  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install uv
        run: curl -LsSf https://astral.sh/uv/install.sh | sh

      - name: Install dependencies
        run: uv sync --extra dev

      - name: Run linter
        run: uv run ruff check .

      - name: Run type checker
        run: uv run mypy src/
```

## Release Process

### Version Management

```python
# pyproject.toml
[project]
name = "cdon-watcher"
version = "1.0.0"
```

### Release Checklist

- [ ] Update version in `pyproject.toml`
- [ ] Update changelog
- [ ] Run full test suite
- [ ] Create git tag
- [ ] Build and test containers
- [ ] Deploy to staging
- [ ] Deploy to production
- [ ] Monitor for issues

### Changelog Format

```markdown
# Changelog

## [1.1.0] - 2025-08-31

### Added

- Discord webhook notifications
- TMDB integration for movie metadata

### Fixed

- Price parsing for promotional text
- Database connection pooling

### Changed

- Updated scraping strategy for better performance

### Removed

- Legacy Flask web interface
```

## Contributing Guidelines

### Getting Started

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Ensure all tests pass
6. Update documentation
7. Submit a pull request

### Code of Conduct

- Be respectful and inclusive
- Provide constructive feedback
- Help newcomers learn
- Focus on solutions, not blame

### Recognition

Contributors will be recognized in:

- GitHub repository contributors
- Changelog for significant contributions
- Project documentation

## Support and Resources

### Getting Help

- **Issues**: GitHub Issues for bugs and feature requests
- **Discussions**: GitHub Discussions for questions
- **Documentation**: This development guide
- **Code Examples**: Test files and example scripts

### Learning Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [SQLModel Documentation](https://sqlmodel.tiangolo.com/)
- [Playwright Documentation](https://playwright.dev/python/docs/intro)
- [Python Async Best Practices](https://asyncio.dev/)

### Development Tools

- **uv**: Fast Python package manager
- **Ruff**: Fast Python linter and formatter
- **mypy**: Static type checker
- **pytest**: Testing framework
- **Playwright**: Browser automation
- **Docker**: Containerization
