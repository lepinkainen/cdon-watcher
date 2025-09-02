# Database Schema Documentation

This document provides comprehensive documentation of the CDON Watcher database schema, including all tables, relationships, indexes, and data models.

## Overview

CDON Watcher uses **SQLite** as its database backend with **SQLModel** (SQLAlchemy + Pydantic) for type-safe database operations. The database file is typically located at `./data/cdon_movies.db`.

## Database Configuration

### Connection Settings

```python
# Default database path
DB_PATH = "./data/cdon_movies.db"

# Async connection using aiosqlite
engine = create_async_engine(f"sqlite+aiosqlite:///{DB_PATH}")
```

### Database Initialization

The database is automatically created and migrated when the application starts:

```python
async def init_db():
    """Initialize database and create tables."""
    async with engine.begin() as conn:
        # Create all tables
        await conn.run_sync(SQLModel.metadata.create_all)
```

## Core Tables

### Movies Table

**Purpose**: Stores information about all tracked movies.

```sql
CREATE TABLE movies (
    id INTEGER PRIMARY KEY,
    product_id TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    format TEXT,
    url TEXT,
    image_url TEXT,
    production_year INTEGER,
    tmdb_id INTEGER,
    content_type TEXT DEFAULT 'movie',
    first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

**Indexes**:

```sql
CREATE UNIQUE INDEX idx_movies_product_id ON movies(product_id);
CREATE INDEX idx_movies_title ON movies(title);
CREATE INDEX idx_movies_tmdb_id ON movies(tmdb_id);
```

**Fields**:

- `id`: Primary key (auto-increment)
- `product_id`: Unique CDON product identifier
- `title`: Movie title
- `format`: Media format (Blu-ray, 4K Blu-ray, etc.)
- `url`: CDON product page URL
- `image_url`: Movie poster image URL
- `production_year`: Year the movie was produced
- `tmdb_id`: The Movie Database ID for metadata
- `content_type`: Content type (default: 'movie')
- `first_seen`: When movie was first discovered
- `last_updated`: Last time movie data was updated

### Price History Table

**Purpose**: Stores historical price data for price tracking and analysis.

```sql
CREATE TABLE price_history (
    id INTEGER PRIMARY KEY,
    movie_id INTEGER NOT NULL,
    product_id TEXT NOT NULL,
    price REAL NOT NULL,
    availability TEXT,
    checked_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (movie_id) REFERENCES movies(id)
);
```

**Indexes**:

```sql
CREATE INDEX idx_price_history_movie_id ON price_history(movie_id);
CREATE INDEX idx_price_history_product_id ON price_history(product_id);
CREATE INDEX idx_price_history_checked_at ON price_history(checked_at);
```

**Fields**:

- `id`: Primary key (auto-increment)
- `movie_id`: Foreign key to movies table
- `product_id`: CDON product identifier (denormalized for performance)
- `price`: Price in euros
- `availability`: Stock status (in stock, out of stock, etc.)
- `checked_at`: When price was checked

### Watchlist Table

**Purpose**: Stores user's watchlist with target prices.

```sql
CREATE TABLE watchlist (
    id INTEGER PRIMARY KEY,
    movie_id INTEGER UNIQUE NOT NULL,
    product_id TEXT UNIQUE NOT NULL,
    target_price REAL NOT NULL,
    notify_on_availability BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (movie_id) REFERENCES movies(id)
);
```

**Indexes**:

```sql
CREATE UNIQUE INDEX idx_watchlist_movie_id ON watchlist(movie_id);
CREATE UNIQUE INDEX idx_watchlist_product_id ON watchlist(product_id);
```

**Fields**:

- `id`: Primary key (auto-increment)
- `movie_id`: Foreign key to movies table (unique)
- `product_id`: CDON product identifier (unique, denormalized)
- `target_price`: User's target price for notifications
- `notify_on_availability`: Whether to notify when back in stock
- `created_at`: When item was added to watchlist

### Price Alerts Table

**Purpose**: Stores price change notifications and alerts.

```sql
CREATE TABLE price_alerts (
    id INTEGER PRIMARY KEY,
    movie_id INTEGER NOT NULL,
    product_id TEXT NOT NULL,
    old_price REAL NOT NULL,
    new_price REAL NOT NULL,
    alert_type TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    notified BOOLEAN DEFAULT 0,
    FOREIGN KEY (movie_id) REFERENCES movies(id)
);
```

**Indexes**:

```sql
CREATE INDEX idx_price_alerts_movie_id ON price_alerts(movie_id);
CREATE INDEX idx_price_alerts_product_id ON price_alerts(product_id);
CREATE INDEX idx_price_alerts_created_at ON price_alerts(created_at);
CREATE INDEX idx_price_alerts_notified ON price_alerts(notified);
```

**Fields**:

- `id`: Primary key (auto-increment)
- `movie_id`: Foreign key to movies table
- `product_id`: CDON product identifier (denormalized)
- `old_price`: Previous price
- `new_price`: New price
- `alert_type`: Type of alert ('price_drop', 'target_reached', 'back_in_stock')
- `created_at`: When alert was created
- `notified`: Whether user has been notified

### Ignored Movies Table

**Purpose**: Stores movies that should be hidden from results.

```sql
CREATE TABLE ignored_movies (
    id INTEGER PRIMARY KEY,
    movie_id INTEGER UNIQUE NOT NULL,
    product_id TEXT UNIQUE NOT NULL,
    ignored_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (movie_id) REFERENCES movies(id)
);
```

**Indexes**:

```sql
CREATE UNIQUE INDEX idx_ignored_movies_movie_id ON ignored_movies(movie_id);
CREATE UNIQUE INDEX idx_ignored_movies_product_id ON ignored_movies(product_id);
```

**Fields**:

- `id`: Primary key (auto-increment)
- `movie_id`: Foreign key to movies table (unique)
- `product_id`: CDON product identifier (unique, denormalized)
- `ignored_at`: When movie was ignored

## Entity-Relationship Diagram

```
┌─────────────┐     ┌─────────────────┐
│   Movies    │────▶│ Price History   │
│             │1   *│                 │
├─────────────┤     ├─────────────────┤
│ id (PK)     │     │ id (PK)         │
│ product_id  │     │ movie_id (FK)   │
│ title       │     │ product_id      │
│ format      │     │ price           │
│ url         │     │ availability    │
│ image_url   │     │ checked_at      │
│ tmdb_id     │     └─────────────────┘
│ first_seen  │              ▲
│ last_updated│              │
└─────────────┘              │
        │1                   │
        │                    │
        ▼                    │
┌─────────────┐     ┌─────────────────┐
│  Watchlist  │     │  Price Alerts   │
│             │     │                 │
├─────────────┤     ├─────────────────┤
│ id (PK)     │     │ id (PK)         │
│ movie_id(FK)│     │ movie_id (FK)   │
│ product_id  │     │ product_id      │
│ target_price│     │ old_price       │
│ notify_...  │     │ new_price       │
│ created_at  │     │ alert_type      │
└─────────────┘     │ created_at      │
                    │ notified        │
                    └─────────────────┘
                             ▲
                             │
                    ┌─────────────────┐
                    │Ignored Movies   │
                    │                 │
                    ├─────────────────┤
                    │ id (PK)         │
                    │ movie_id (FK)   │
                    │ product_id      │
                    │ ignored_at      │
                    └─────────────────┘
```

## SQLModel Models

### Movie Model

```python
class Movie(SQLModel, table=True):
    """Movie model representing the movies table."""

    __tablename__ = "movies"

    id: int | None = Field(default=None, primary_key=True)
    product_id: str = Field(unique=True, index=True)
    title: str
    format: str | None = None
    url: str | None = None
    image_url: str | None = None
    production_year: int | None = None
    tmdb_id: int | None = None
    content_type: str = Field(default="movie")
    first_seen: datetime = Field(default_factory=datetime.utcnow)
    last_updated: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    price_history: list["PriceHistory"] = Relationship(back_populates="movie")
    watchlist_entries: list["Watchlist"] = Relationship(back_populates="movie")
    price_alerts: list["PriceAlert"] = Relationship(back_populates="movie")
    ignored_entries: list["IgnoredMovie"] = Relationship(back_populates="movie")
```

### PriceHistory Model

```python
class PriceHistory(SQLModel, table=True):
    """Price history model representing the price_history table."""

    __tablename__ = "price_history"

    id: int | None = Field(default=None, primary_key=True)
    movie_id: int = Field(foreign_key="movies.id", index=True)
    product_id: str = Field(index=True)
    price: float
    availability: str | None = None
    checked_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    movie: Movie | None = Relationship(back_populates="price_history")
```

### Watchlist Model

```python
class Watchlist(SQLModel, table=True):
    """Watchlist model representing the watchlist table."""

    __tablename__ = "watchlist"

    id: int | None = Field(default=None, primary_key=True)
    movie_id: int = Field(foreign_key="movies.id", unique=True)
    product_id: str = Field(unique=True, index=True)
    target_price: float
    notify_on_availability: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    movie: Movie | None = Relationship(back_populates="watchlist_entries")
```

### PriceAlert Model

```python
class PriceAlert(SQLModel, table=True):
    """Price alert model representing the price_alerts table."""

    __tablename__ = "price_alerts"

    id: int | None = Field(default=None, primary_key=True)
    movie_id: int = Field(foreign_key="movies.id", index=True)
    product_id: str = Field(index=True)
    old_price: float
    new_price: float
    alert_type: str  # 'price_drop', 'back_in_stock', 'target_reached'
    created_at: datetime = Field(default_factory=datetime.utcnow)
    notified: bool = Field(default=False)

    # Relationships
    movie: Movie | None = Relationship(back_populates="price_alerts")
```

### IgnoredMovie Model

```python
class IgnoredMovie(SQLModel, table=True):
    """Ignored movie model representing the ignored_movies table."""

    __tablename__ = "ignored_movies"

    id: int | None = Field(default=None, primary_key=True)
    movie_id: int = Field(foreign_key="movies.id", unique=True)
    product_id: str = Field(unique=True, index=True)
    ignored_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    movie: Movie | None = Relationship(back_populates="ignored_entries")
```

## API Response Models

### MovieWithPricing

Used for movie search results with pricing information:

```python
class MovieWithPricing(SQLModel):
    """Movie model with pricing information for API responses."""

    id: int
    product_id: str
    title: str
    format: str | None = None
    url: str | None = None
    image_url: str | None = None
    production_year: int | None = None
    tmdb_id: int | None = None
    content_type: str = "movie"
    first_seen: datetime
    last_updated: datetime
    current_price: float | None = None
    lowest_price: float | None = None
    highest_price: float | None = None
```

### DealMovie

Used for deals endpoint with price change information:

```python
class DealMovie(SQLModel):
    """Movie model specifically for deals with price change information."""

    id: int
    product_id: str
    title: str
    format: str | None = None
    url: str | None = None
    image_url: str | None = None
    production_year: int | None = None
    tmdb_id: int | None = None
    current_price: float
    previous_price: float
    price_change: float
    lowest_price: float
    highest_price: float
```

### WatchlistMovie

Used for watchlist items with target price information:

```python
class WatchlistMovie(SQLModel):
    """Movie model for watchlist items with target price."""

    id: int
    product_id: str
    title: str
    format: str | None = None
    url: str | None = None
    image_url: str | None = None
    production_year: int | None = None
    tmdb_id: int | None = None
    content_type: str = "movie"
    first_seen: datetime
    last_updated: datetime
    target_price: float
    current_price: float | None = None
    lowest_price: float | None = None
    highest_price: float | None = None
```

### PriceAlertWithTitle

Used for alerts with movie title included:

```python
class PriceAlertWithTitle(SQLModel):
    """Price alert model with movie title included."""

    id: int
    movie_id: int
    product_id: str
    old_price: float
    new_price: float
    alert_type: str
    created_at: datetime
    notified: bool
    movie_title: str
```

### StatsData

Used for dashboard statistics:

```python
class StatsData(SQLModel):
    """Dashboard statistics data model."""

    total_movies: int
    price_drops_today: int
    watchlist_count: int
    last_update: str | None = None
```

## Database Operations

### Repository Pattern

The application uses a repository pattern for database operations:

```python
class DatabaseRepository:
    """Repository for database operations."""

    def __init__(self, session: AsyncSession, enable_query_logging: bool = False):
        self.session = session
        self.enable_query_logging = enable_query_logging

    # Movie operations
    async def get_movie_by_product_id(self, product_id: str) -> Movie | None:
        """Get movie by product ID."""

    async def create_movie(self, movie_data: dict) -> Movie:
        """Create new movie."""

    async def update_movie(self, movie: Movie, update_data: dict) -> Movie:
        """Update movie data."""

    # Price operations
    async def add_price_history(self, movie_id: int, price: float, availability: str | None = None) -> PriceHistory:
        """Add price history entry."""

    async def get_price_history(self, movie_id: int, limit: int = 50) -> list[PriceHistory]:
        """Get price history for movie."""

    # Watchlist operations
    async def add_to_watchlist(self, product_id: str, target_price: float) -> bool:
        """Add movie to watchlist."""

    async def remove_from_watchlist(self, product_id: str) -> bool:
        """Remove movie from watchlist."""

    async def get_watchlist(self) -> list[WatchlistMovie]:
        """Get all watchlist items with pricing."""

    # Alert operations
    async def create_price_alert(self, movie_id: int, old_price: float, new_price: float, alert_type: str) -> PriceAlert:
        """Create price alert."""

    async def get_price_alerts(self, limit: int = 10) -> list[PriceAlertWithTitle]:
        """Get recent price alerts."""

    # Search operations
    async def search_movies(self, query: str, limit: int = 20) -> list[MovieWithPricing]:
        """Search movies by title, format, or price."""

    # Statistics
    async def get_stats(self) -> StatsData:
        """Get dashboard statistics."""
```

## Query Examples

### Common Queries

#### Get Movie with Price History

```sql
SELECT m.*, ph.price, ph.checked_at
FROM movies m
LEFT JOIN price_history ph ON m.id = ph.movie_id
WHERE m.product_id = ?
ORDER BY ph.checked_at DESC
LIMIT 10;
```

#### Find Price Drops

```sql
SELECT m.title, ph1.price as old_price, ph2.price as new_price,
       (ph2.price - ph1.price) as price_change
FROM movies m
JOIN price_history ph1 ON m.id = ph1.movie_id
JOIN price_history ph2 ON m.id = ph2.movie_id
WHERE ph1.checked_at < ph2.checked_at
  AND ph2.price < ph1.price
  AND ph2.checked_at >= datetime('now', '-1 day')
ORDER BY (ph2.price - ph1.price) ASC;
```

#### Watchlist with Current Prices

```sql
SELECT m.*, w.target_price, ph.price as current_price,
       ph.price <= w.target_price as target_reached
FROM watchlist w
JOIN movies m ON w.movie_id = m.id
LEFT JOIN (
    SELECT movie_id, price
    FROM price_history
    WHERE (movie_id, checked_at) IN (
        SELECT movie_id, MAX(checked_at)
        FROM price_history
        GROUP BY movie_id
    )
) ph ON m.id = ph.movie_id;
```

### Performance Optimization

#### Indexes for Common Queries

```sql
-- Search optimization
CREATE INDEX idx_movies_title_fts ON movies(title);
CREATE VIRTUAL TABLE movies_fts USING fts5(title, content='movies', content_rowid='id');

-- Price analysis
CREATE INDEX idx_price_history_movie_date ON price_history(movie_id, checked_at);
CREATE INDEX idx_price_history_price ON price_history(price);

-- Watchlist queries
CREATE INDEX idx_watchlist_target_price ON watchlist(target_price);
```

#### Query Optimization Tips

1. **Use EXPLAIN QUERY PLAN** to analyze query execution
2. **Denormalize** frequently accessed data (product_id in related tables)
3. **Use appropriate indexes** for WHERE clauses and JOINs
4. **Limit result sets** for large tables
5. **Use UNION ALL** instead of UNION when possible

## Data Integrity

### Constraints

- **Primary Keys**: Auto-incrementing integers
- **Foreign Keys**: Enforced referential integrity
- **Unique Constraints**: Prevent duplicate entries
- **Check Constraints**: Validate data ranges

### Data Validation

```python
# Example validation in SQLModel
price: float = Field(gt=0, le=1000)  # Price between 0 and 1000
target_price: float = Field(gt=0)     # Positive target price
product_id: str = Field(min_length=1, max_length=100)  # Valid product ID
```

## Backup and Recovery

### Database Backup

```bash
# SQLite backup (while database is not in use)
sqlite3 data/cdon_movies.db ".backup backup.db"

# Or using SQL
.backup backup.db
```

### Database Restore

```bash
# Restore from backup
sqlite3 data/cdon_movies.db ".restore backup.db"
```

### Export/Import Data

```bash
# Export to SQL
sqlite3 data/cdon_movies.db .dump > database_dump.sql

# Import from SQL
sqlite3 new_database.db < database_dump.sql
```

## Maintenance

### Database Vacuum

```sql
-- Reclaim unused space
VACUUM;

-- Analyze for query optimization
ANALYZE;
```

### Index Maintenance

```sql
-- Rebuild indexes
REINDEX;

-- Check index fragmentation
PRAGMA index_info(index_name);
```

### Size Monitoring

```sql
-- Database file size
SELECT page_count * page_size as size_bytes FROM pragma_page_count(), pragma_page_size();

-- Table sizes
SELECT name, SUM(pgsize) as size
FROM dbstat
GROUP BY name
ORDER BY size DESC;
```

## Migration Strategy

### Schema Changes

When making schema changes:

1. **Create migration scripts** for incremental changes
2. **Test migrations** on development data
3. **Backup database** before applying migrations
4. **Apply migrations** during deployment
5. **Verify data integrity** after migration

### Example Migration

```python
async def migrate_add_tmdb_id():
    """Add TMDB ID column to movies table."""

    # Add column if it doesn't exist
    await session.execute(text("""
        ALTER TABLE movies
        ADD COLUMN tmdb_id INTEGER;
    """))

    # Create index
    await session.execute(text("""
        CREATE INDEX idx_movies_tmdb_id ON movies(tmdb_id);
    """))

    await session.commit()
```

## Performance Metrics

### Database Performance

- **Query Response Time**: < 100ms for most queries
- **Concurrent Connections**: SQLite supports multiple readers
- **Write Performance**: ~1000 writes/second
- **Storage Efficiency**: ~1KB per movie record

### Optimization Targets

- **Search Queries**: < 50ms response time
- **Dashboard Stats**: < 200ms response time
- **Price Updates**: < 10ms per movie
- **Bulk Operations**: < 5 seconds for 1000 movies

## Monitoring

### Database Health Checks

```python
async def check_database_health():
    """Check database connectivity and performance."""

    # Test connection
    await session.execute(text("SELECT 1"))

    # Check table counts
    result = await session.execute(text("SELECT COUNT(*) FROM movies"))
    movie_count = result.scalar()

    # Check recent activity
    result = await session.execute(text("""
        SELECT COUNT(*) FROM price_history
        WHERE checked_at >= datetime('now', '-1 hour')
    """))
    recent_checks = result.scalar()

    return {
        "status": "healthy",
        "movie_count": movie_count,
        "recent_activity": recent_checks
    }
```

### Performance Monitoring

```python
async def log_slow_queries(query, duration):
    """Log queries that exceed performance thresholds."""

    if duration > 1.0:  # Log queries > 1 second
        logger.warning(f"Slow query ({duration:.2f}s): {query}")
```

## Troubleshooting

### Common Issues

#### Database Lock Errors

```sql
-- Check for locks
PRAGMA lock_status;

-- Kill long-running queries
SELECT * FROM sqlite_master;
```

#### Corruption Issues

```bash
# Check for corruption
sqlite3 data/cdon_movies.db "PRAGMA integrity_check;"

# Recover from corruption
sqlite3 data/cdon_movies.db ".recover" | sqlite3 recovered.db
```

#### Performance Issues

```sql
-- Analyze query performance
EXPLAIN QUERY PLAN SELECT * FROM movies WHERE title LIKE '%batman%';

-- Check index usage
PRAGMA index_list(movies);
```

## Best Practices

### Design Principles

1. **Normalization**: Proper table relationships
2. **Indexing**: Strategic indexes for performance
3. **Constraints**: Data integrity enforcement
4. **Documentation**: Clear schema documentation

### Operational Guidelines

1. **Regular Backups**: Automated backup procedures
2. **Monitoring**: Performance and health monitoring
3. **Maintenance**: Regular vacuum and analyze operations
4. **Migration Planning**: Careful schema change management

### Development Guidelines

1. **Type Safety**: Use SQLModel for type checking
2. **Async Operations**: All database operations are async
3. **Error Handling**: Comprehensive error handling
4. **Testing**: Unit and integration tests for database operations
