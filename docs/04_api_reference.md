# API Reference

This document provides comprehensive documentation for the CDON Watcher REST API, including all endpoints, request/response formats, and usage examples.

## Base URL

```
http://localhost:8080/api
```

All API endpoints are prefixed with `/api`. The default port is 8080 but can be configured via the `API_PORT` environment variable.

## Authentication

The API currently does not require authentication. All endpoints are publicly accessible.

## Response Format

All API responses follow a consistent JSON format:

### Success Response

```json
{
  "data": { ... },
  "message": "Optional success message",
  "status": "success"
}
```

### Error Response

```json
{
  "detail": "Error description",
  "status": "error"
}
```

## Endpoints

### Statistics

#### GET /api/stats

Get dashboard statistics including movie counts, alerts, and system information.

**Response:**

```json
{
  "total_movies": 1250,
  "price_drops_today": 5,
  "watchlist_count": 15,
  "last_update": "2025-08-31T22:00:00Z"
}
```

**Example:**

```bash
curl http://localhost:8080/api/stats
```

### Alerts

#### GET /api/alerts

Get recent price alerts with pagination support.

**Query Parameters:**

- `limit` (optional): Number of alerts to return (default: 10, max: 100)
- `offset` (optional): Pagination offset (default: 0)

**Response:**

```json
[
  {
    "id": 1,
    "movie_id": 123,
    "product_id": "MOVIE_001",
    "old_price": 29.99,
    "new_price": 24.99,
    "alert_type": "price_drop",
    "created_at": "2025-08-31T20:30:00Z",
    "notified": false,
    "movie_title": "Inception"
  }
]
```

**Examples:**

```bash
# Get latest 10 alerts
curl http://localhost:8080/api/alerts

# Get 20 alerts with offset
curl "http://localhost:8080/api/alerts?limit=20&offset=10"
```

### Deals

#### GET /api/deals

Get movies with the biggest recent price drops.

**Query Parameters:**

- `limit` (optional): Number of deals to return (default: 12, max: 50)

**Response:**

```json
[
  {
    "id": 456,
    "product_id": "MOVIE_456",
    "title": "The Dark Knight",
    "format": "Blu-ray",
    "url": "https://cdon.fi/movie/dark-knight",
    "image_url": "https://cdon.fi/images/dark-knight.jpg",
    "current_price": 19.99,
    "previous_price": 29.99,
    "price_change": -10.0,
    "lowest_price": 17.99,
    "highest_price": 34.99
  }
]
```

**Example:**

```bash
curl http://localhost:8080/api/deals
```

### Watchlist

#### GET /api/watchlist

Get all movies in the user's watchlist.

**Response:**

```json
[
  {
    "id": 789,
    "product_id": "MOVIE_789",
    "title": "Interstellar",
    "format": "4K Blu-ray",
    "url": "https://cdon.fi/movie/interstellar-4k",
    "image_url": "https://cdon.fi/images/interstellar.jpg",
    "tmdb_id": 157336,
    "content_type": "movie",
    "first_seen": "2025-01-15T10:00:00Z",
    "last_updated": "2025-08-31T21:00:00Z",
    "target_price": 25.99,
    "current_price": 29.99,
    "lowest_price": 22.99,
    "highest_price": 39.99
  }
]
```

**Example:**

```bash
curl http://localhost:8080/api/watchlist
```

#### POST /api/watchlist

Add a movie to the watchlist.

**Request Body:**

```json
{
  "product_id": "MOVIE_789",
  "target_price": 25.99
}
```

**Response:**

```json
{
  "message": "Added to watchlist",
  "status": "success"
}
```

**Examples:**

```bash
# Add movie to watchlist
curl -X POST http://localhost:8080/api/watchlist \
  -H "Content-Type: application/json" \
  -d '{"product_id": "MOVIE_789", "target_price": 25.99}'

# Error response for missing product_id
{
  "detail": "Missing product_id",
  "status": "error"
}
```

#### DELETE /api/watchlist/{product_id}

Remove a movie from the watchlist.

**Path Parameters:**

- `product_id`: The product ID of the movie to remove

**Response:**

```json
{
  "message": "Removed from watchlist",
  "status": "success"
}
```

**Examples:**

```bash
# Remove movie from watchlist
curl -X DELETE http://localhost:8080/api/watchlist/MOVIE_789

# Error response for non-existent movie
{
  "detail": "Movie not found in watchlist",
  "status": "error"
}
```

### Search

#### GET /api/search

Search for movies by title, format, or price criteria.

**Query Parameters:**

- `q`: Search query (required)
- `limit` (optional): Maximum results to return (default: 20, max: 100)

**Search Syntax:**

- **Title search**: `q=Inception` - searches movie titles
- **Format search**: `q=4K` or `q=blu-ray` - filters by format
- **Price search**: `q=under 20` - finds movies under €20
- **Combined**: `q=4K under 30` - 4K movies under €30

**Response:**

```json
[
  {
    "id": 123,
    "product_id": "MOVIE_123",
    "title": "Inception",
    "format": "Blu-ray",
    "url": "https://cdon.fi/movie/inception",
    "image_url": "https://cdon.fi/images/inception.jpg",
    "tmdb_id": 27205,
    "content_type": "movie",
    "first_seen": "2025-01-10T08:00:00Z",
    "last_updated": "2025-08-31T19:00:00Z",
    "current_price": 24.99,
    "lowest_price": 19.99,
    "highest_price": 34.99
  }
]
```

**Examples:**

```bash
# Search by title
curl "http://localhost:8080/api/search?q=Inception"

# Search by format
curl "http://localhost:8080/api/search?q=4K"

# Search by price
curl "http://localhost:8080/api/search?q=under 20"

# Combined search
curl "http://localhost:8080/api/search?q=4K under 30"

# Limited results
curl "http://localhost:8080/api/search?q=batman&limit=5"
```

### Cheapest Movies

#### GET /api/cheapest-blurays

Get the cheapest Blu-ray movies.

**Query Parameters:**

- `limit` (optional): Number of movies to return (default: 20, max: 100)

**Response:**

```json
[
  {
    "id": 101,
    "product_id": "MOVIE_101",
    "title": "The Shawshank Redemption",
    "format": "Blu-ray",
    "url": "https://cdon.fi/movie/shawshank",
    "image_url": "https://cdon.fi/images/shawshank.jpg",
    "tmdb_id": 278,
    "content_type": "movie",
    "first_seen": "2025-02-01T12:00:00Z",
    "last_updated": "2025-08-31T18:00:00Z",
    "current_price": 12.99,
    "lowest_price": 12.99,
    "highest_price": 24.99
  }
]
```

**Example:**

```bash
curl "http://localhost:8080/api/cheapest-blurays?limit=10"
```

#### GET /api/cheapest-4k-blurays

Get the cheapest 4K Blu-ray movies.

**Query Parameters:**

- `limit` (optional): Number of movies to return (default: 20, max: 100)

**Response:** Same format as `/api/cheapest-blurays`

**Example:**

```bash
curl "http://localhost:8080/api/cheapest-4k-blurays?limit=10"
```

### Movie Management

#### POST /api/ignore-movie

Add a movie to the ignored list (hide from results).

**Request Body:**

```json
{
  "product_id": "MOVIE_999"
}
```

**Response:**

```json
{
  "message": "Movie ignored",
  "status": "success"
}
```

**Example:**

```bash
curl -X POST http://localhost:8080/api/ignore-movie \
  -H "Content-Type: application/json" \
  -d '{"product_id": "MOVIE_999"}'
```

## Data Models

### Movie

```json
{
  "id": "integer (primary key)",
  "product_id": "string (unique)",
  "title": "string",
  "format": "string | null",
  "url": "string | null",
  "image_url": "string | null",
  "tmdb_id": "integer | null",
  "content_type": "string (default: 'movie')",
  "first_seen": "datetime",
  "last_updated": "datetime"
}
```

### PriceHistory

```json
{
  "id": "integer (primary key)",
  "movie_id": "integer (foreign key)",
  "product_id": "string",
  "price": "float",
  "availability": "string | null",
  "checked_at": "datetime"
}
```

### Watchlist

```json
{
  "id": "integer (primary key)",
  "movie_id": "integer (foreign key, unique)",
  "product_id": "string (unique)",
  "target_price": "float",
  "notify_on_availability": "boolean (default: true)",
  "created_at": "datetime"
}
```

### PriceAlert

```json
{
  "id": "integer (primary key)",
  "movie_id": "integer (foreign key)",
  "product_id": "string",
  "old_price": "float",
  "new_price": "float",
  "alert_type": "string ('price_drop', 'back_in_stock', 'target_reached')",
  "created_at": "datetime",
  "notified": "boolean (default: false)"
}
```

### StatsData

```json
{
  "total_movies": "integer",
  "price_drops_today": "integer",
  "watchlist_count": "integer",
  "last_update": "string | null"
}
```

## Error Handling

### HTTP Status Codes

- **200 OK**: Successful request
- **400 Bad Request**: Invalid request parameters
- **404 Not Found**: Resource not found
- **500 Internal Server Error**: Server error

### Common Error Responses

```json
// Invalid request
{
  "detail": "Missing required parameter: product_id",
  "status": "error"
}

// Not found
{
  "detail": "Movie not found",
  "status": "error"
}

// Server error
{
  "detail": "Database connection failed",
  "status": "error"
}
```

## Rate Limiting

The API currently does not implement rate limiting. However, consider the following best practices:

- Limit requests to reasonable intervals
- Implement caching for frequently accessed data
- Use pagination for large result sets

## Pagination

Endpoints that return multiple items support pagination:

- `limit`: Maximum items per page (default varies by endpoint)
- `offset`: Number of items to skip (default: 0)

```bash
# Get first 20 results
curl "http://localhost:8080/api/search?q=movie&limit=20&offset=0"

# Get next 20 results
curl "http://localhost:8080/api/search?q=movie&limit=20&offset=20"
```

## Content Types

### Request Content Types

- `application/json`: For POST/PUT requests with JSON body
- `application/x-www-form-urlencoded`: For form data (not commonly used)

### Response Content Types

- `application/json`: All API responses are JSON
- `text/html`: Web dashboard pages (non-API routes)

## CORS Support

The API includes CORS (Cross-Origin Resource Sharing) support:

- **Allowed Origins**: `*` (all origins)
- **Allowed Methods**: `GET`, `POST`, `PUT`, `DELETE`, `OPTIONS`
- **Allowed Headers**: `*` (all headers)
- **Credentials**: Supported

## Examples

### Python Client

```python
import requests

class CDONWatcherAPI:
    def __init__(self, base_url="http://localhost:8080"):
        self.base_url = base_url

    def get_stats(self):
        response = requests.get(f"{self.base_url}/api/stats")
        return response.json()

    def search_movies(self, query, limit=20):
        params = {"q": query, "limit": limit}
        response = requests.get(f"{self.base_url}/api/search", params=params)
        return response.json()

    def add_to_watchlist(self, product_id, target_price):
        data = {"product_id": product_id, "target_price": target_price}
        response = requests.post(f"{self.base_url}/api/watchlist", json=data)
        return response.json()

    def get_watchlist(self):
        response = requests.get(f"{self.base_url}/api/watchlist")
        return response.json()

# Usage
api = CDONWatcherAPI()
stats = api.get_stats()
movies = api.search_movies("Inception")
api.add_to_watchlist("MOVIE_123", 19.99)
```

### JavaScript Client

```javascript
class CDONWatcherAPI {
  constructor(baseURL = 'http://localhost:8080') {
    this.baseURL = baseURL
  }

  async getStats() {
    const response = await fetch(`${this.baseURL}/api/stats`)
    return response.json()
  }

  async searchMovies(query, limit = 20) {
    const params = new URLSearchParams({ q: query, limit })
    const response = await fetch(`${this.baseURL}/api/search?${params}`)
    return response.json()
  }

  async addToWatchlist(productId, targetPrice) {
    const response = await fetch(`${this.baseURL}/api/watchlist`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        product_id: productId,
        target_price: targetPrice,
      }),
    })
    return response.json()
  }

  async getWatchlist() {
    const response = await fetch(`${this.baseURL}/api/watchlist`)
    return response.json()
  }
}

// Usage
const api = new CDONWatcherAPI()
api.getStats().then((stats) => console.log(stats))
api.searchMovies('Batman').then((movies) => console.log(movies))
```

## WebSocket Support

The API does not currently support WebSocket connections. For real-time updates, consider polling the relevant endpoints at appropriate intervals.

## Versioning

The API does not currently implement versioning. All endpoints are considered part of version 1.0.0. Future breaking changes will be communicated through:

- Release notes
- Migration guides
- Deprecation warnings in response headers

## Support

For API-related issues or questions:

1. Check the application logs for error details
2. Verify request format and parameters
3. Test with the provided examples
4. Review the [Troubleshooting Guide](08_troubleshooting.md) for common issues

## Changelog

### Version 1.0.0

- Initial API release
- Core endpoints for movies, watchlist, and alerts
- Search and statistics functionality
- Basic error handling and response formatting
