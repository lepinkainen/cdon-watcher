# FastAPI + SQLModel Migration Plan

A detailed plan to convert the CDON Watcher project from Flask to FastAPI with SQLModel.

## Overview

This migration will modernize the web API layer while maintaining backward compatibility. The current Flask application with raw SQLite queries will be replaced with FastAPI and SQLModel for better type safety, performance, and developer experience.

## Migration Phases

### Phase 1: Dependency & Model Setup

- [ ] **Update pyproject.toml dependencies**
  - Add `fastapi>=0.104.0`
  - Add `sqlmodel>=0.0.14`  
  - Add `uvicorn[standard]>=0.24.0` (ASGI server)
  - Add `aiosqlite>=0.19.0` (async SQLite driver)
  - Remove `flask>=3.0.0` and `flask-cors>=4.0.0`

- [ ] **Create SQLModel models** (`src/cdon_watcher/models.py`)
  - `Movie` model (maps to `movies` table)
  - `PriceHistory` model (maps to `price_history` table)
  - `Watchlist` model (maps to `watchlist` table)
  - `PriceAlert` model (maps to `price_alerts` table)
  - `IgnoredMovie` model (maps to `ignored_movies` table)
  - Define proper relationships between models

- [ ] **Database connection setup** (`src/cdon_watcher/database/connection.py`)
  - Create async SQLAlchemy engine with aiosqlite
  - Replace `DatabaseManager.get_connection()` with async session factory
  - Implement database initialization for SQLModel

### Phase 2: API Layer Migration

- [ ] **Create FastAPI application** (`src/cdon_watcher/web/app.py`)
  - Replace Flask app factory with FastAPI instance
  - Configure CORS middleware
  - Add static file mounting for posters and web assets
  - Set up OpenAPI documentation

- [ ] **Convert API routes** (`src/cdon_watcher/web/routes.py`)
  - Convert 12 Flask routes to FastAPI router functions:
    - `GET /api/stats` - Dashboard statistics
    - `GET /api/alerts` - Recent price alerts  
    - `GET /api/deals` - Movies with biggest price drops
    - `GET /api/watchlist` - Watchlist operations (GET/POST)
    - `DELETE /api/watchlist/{identifier}` - Remove from watchlist
    - `GET /api/search` - Movie search
    - `GET /api/cheapest-blurays` - Cheapest Blu-ray movies
    - `GET /api/cheapest-4k-blurays` - Cheapest 4K Blu-ray movies
    - `POST /api/ignore-movie` - Add movie to ignored list
    - `GET /posters/{filename}` - Serve poster images
    - `GET /` - Main dashboard page

- [ ] **Create Pydantic models** (`src/cdon_watcher/schemas.py`)
  - Request models: `WatchlistRequest`, `IgnoreMovieRequest`, `SearchParams`
  - Response models: `StatsResponse`, `MovieResponse`, `DealResponse`, `WatchlistResponse`
  - Error response models for consistent API responses

### Phase 3: Database Layer Refactoring

- [ ] **Replace DatabaseManager class** (`src/cdon_watcher/database/repository.py`)
  - Convert `get_stats()` to use SQLModel queries
  - Convert `get_deals()` to use SQLModel queries with relationships
  - Convert `get_watchlist()` to use SQLModel queries
  - Convert `add_to_watchlist()` / `remove_from_watchlist()` to SQLModel operations
  - Convert search and filtering methods to SQLModel queries
  - Convert ignore functionality to SQLModel operations

- [ ] **Make database operations async**
  - Update all database methods to use `async def` and `await`
  - Replace `sqlite3.connect()` calls with async session management
  - Update error handling for async database exceptions

- [ ] **Update dependent services**
  - **CDONScraper** (`cdon_scraper.py`): Update database calls to async
  - **PriceMonitor** (`monitoring_service.py`): Update database calls to async  
  - **NotificationService** (`notifications.py`): Update if it uses database directly

### Phase 4: Integration & Testing

- [ ] **Update CLI interface** (`src/cdon_watcher/cli.py`)
  - Ensure `web` command works with FastAPI + Uvicorn
  - Update startup command from Flask development server to Uvicorn
  - Maintain backward compatibility for existing CLI usage

- [ ] **Update container configuration**
  - **Dockerfile**: Update startup command to use Uvicorn instead of Flask
  - **docker-compose.yml**: Update web service command
  - **nginx.conf**: Ensure reverse proxy works with FastAPI (should be transparent)
  - Update health checks if needed

- [ ] **Migrate test suite**
  - Update imports from Flask test client to FastAPI TestClient
  - Convert sync test functions to async where database is involved
  - Update test fixtures for async database sessions
  - Ensure `task test` and `task test-integration` still work

- [ ] **Verify build pipeline**
  - Run `task build` to ensure linting and type checking pass
  - Update mypy configuration for FastAPI/SQLModel if needed
  - Ensure all existing functionality works through containers

## Technical Details

### Database Schema Compatibility

The existing SQLite schema will remain unchanged:

- `movies` table with `product_id` as unique identifier
- `price_history` table for tracking price changes
- `watchlist` table for user's tracked items
- `price_alerts` table for notifications
- `ignored_movies` table for filtered content

### API Compatibility

All existing API endpoints will maintain the same:

- URL paths (`/api/stats`, `/api/watchlist`, etc.)
- HTTP methods (GET, POST, DELETE)
- Request/response JSON structure
- Error response format

### Configuration Compatibility

Environment variables remain unchanged:

- `FLASK_HOST` → `API_HOST` (optional rename)
- `FLASK_PORT` → `API_PORT` (optional rename)
- All other config variables stay the same

### Deployment Compatibility

Container deployment remains the same:

- Same ports (8080 for web service)
- Same volume mounts (`./data` for database and posters)
- Same service orchestration via docker-compose

## Benefits of Migration

### Type Safety

- Pydantic validation for all API requests and responses
- SQLModel provides full typing for database operations
- Better IDE support and error detection

### Performance  

- Async/await throughout the request lifecycle
- Better concurrency for database operations
- FastAPI's automatic validation is faster than manual Flask validation

### Developer Experience

- Automatic OpenAPI/Swagger documentation at `/docs`
- Better error messages and validation feedback
- Modern Python patterns with async/await

### Maintainability

- Cleaner separation of concerns with Pydantic schemas
- Type-safe database queries reduce runtime errors  
- Better testing capabilities with FastAPI TestClient

## Risk Mitigation

### Backward Compatibility

- Keep existing API contract unchanged
- Maintain same CLI interface
- Same container configuration and environment variables

### Testing Strategy

- Run existing integration tests against new FastAPI endpoints
- Test web dashboard functionality remains identical
- Verify container-based deployment works unchanged

### Rollback Plan

- Keep original Flask code in git history
- Database schema unchanged, so data is preserved
- Container configuration allows easy service rollback

## Implementation Notes

### Dependencies

Current core dependencies that will change:

```toml
# Remove
flask = ">=3.0.0"
flask-cors = ">=4.0.0"

# Add  
fastapi = ">=0.104.0"
sqlmodel = ">=0.0.14"
uvicorn = {extras = ["standard"], version = ">=0.24.0"}
aiosqlite = ">=0.19.0"
```

### Key Files Modified

- `src/cdon_watcher/web/app.py` - FastAPI app instead of Flask
- `src/cdon_watcher/web/routes.py` - FastAPI router instead of Blueprint
- `src/cdon_watcher/database.py` - SQLModel instead of raw SQL
- `pyproject.toml` - Updated dependencies
- `Dockerfile` - Uvicorn instead of Flask command

### Files Added

- `src/cdon_watcher/models.py` - SQLModel database models
- `src/cdon_watcher/schemas.py` - Pydantic request/response models  
- `src/cdon_watcher/database/connection.py` - Async database setup

This migration maintains full backward compatibility while modernizing the codebase for better maintainability and performance.
