"""FastAPI routes for the web dashboard."""

import os

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from ..config import CONFIG
from ..database.connection import get_db_session
from ..database.repository import DatabaseRepository
from ..models import (
    DealMovie,
    MovieWithPricing,
    PriceAlertWithTitle,
    StatsData,
    WatchlistMovie,
)
from ..schemas import (
    ErrorResponse,
    IgnoreMovieRequest,
    SuccessResponse,
    WatchlistRequest,
)

# Create router
router = APIRouter()


# Dependency function for DatabaseRepository
async def get_repository(session: AsyncSession = Depends(get_db_session)) -> DatabaseRepository:
    """Get DatabaseRepository instance."""
    # Enable query logging in development mode (can be controlled via environment variable)
    enable_logging = CONFIG.get("debug", False) or CONFIG.get("enable_query_logging", False)
    return DatabaseRepository(session, enable_query_logging=enable_logging)


@router.get("/")
async def index(request: Request) -> Response:
    """Main dashboard page."""
    # Get templates from app state
    templates: Jinja2Templates = request.app.state.templates
    return templates.TemplateResponse(request, "index.html")


@router.get("/api/stats", response_model=StatsData)
async def api_stats(repo: DatabaseRepository = Depends(get_repository)) -> StatsData:
    """Get dashboard statistics."""
    stats = await repo.get_stats()
    return stats


@router.get("/api/alerts", response_model=list[PriceAlertWithTitle])
async def api_alerts(
    repo: DatabaseRepository = Depends(get_repository),
) -> list[PriceAlertWithTitle]:
    """Get recent price alerts."""
    alerts = await repo.get_price_alerts(10)
    return alerts


@router.get("/api/deals", response_model=list[DealMovie])
async def api_deals(repo: DatabaseRepository = Depends(get_repository)) -> list[DealMovie]:
    """Get movies with biggest price drops."""
    deals = await repo.get_deals(12)
    return deals


@router.get("/api/watchlist", response_model=list[WatchlistMovie])
async def api_get_watchlist(
    repo: DatabaseRepository = Depends(get_repository),
) -> list[WatchlistMovie]:
    """Get watchlist items."""
    watchlist = await repo.get_watchlist()
    return watchlist


@router.post("/api/watchlist")
async def api_add_to_watchlist(
    request: WatchlistRequest, repo: DatabaseRepository = Depends(get_repository)
) -> SuccessResponse | ErrorResponse:
    """Add item to watchlist."""
    if not request.target_price:
        raise HTTPException(status_code=400, detail="Missing target_price")

    if not request.product_id:
        raise HTTPException(status_code=400, detail="Missing product_id")

    success = await repo.add_to_watchlist(request.product_id, request.target_price)

    if success:
        return SuccessResponse(message="Added to watchlist")
    else:
        raise HTTPException(status_code=500, detail="Failed to add to watchlist")


@router.delete("/api/watchlist/{product_id}")
async def api_remove_from_watchlist(
    product_id: str, repo: DatabaseRepository = Depends(get_repository)
) -> SuccessResponse:
    """Remove movie from watchlist by product_id."""
    success = await repo.remove_from_watchlist(product_id)

    if success:
        return SuccessResponse(message="Removed from watchlist")
    else:
        raise HTTPException(status_code=500, detail="Failed to remove from watchlist")


@router.get("/api/search", response_model=list[MovieWithPricing])
async def api_search(
    q: str = Query(..., description="Search query"),
    repo: DatabaseRepository = Depends(get_repository),
) -> list[MovieWithPricing]:
    """Search for movies."""
    if not q:
        return []

    movies = await repo.search_movies(q, 20)
    return movies


@router.get("/api/cheapest-blurays", response_model=list[MovieWithPricing])
async def api_cheapest_blurays(
    repo: DatabaseRepository = Depends(get_repository),
) -> list[MovieWithPricing]:
    """Get cheapest Blu-ray movies."""
    movies = await repo.get_cheapest_blurays(21)
    return movies


@router.get("/api/cheapest-4k-blurays", response_model=list[MovieWithPricing])
async def api_cheapest_4k_blurays(
    repo: DatabaseRepository = Depends(get_repository),
) -> list[MovieWithPricing]:
    """Get cheapest 4K Blu-ray movies."""
    movies = await repo.get_cheapest_4k_blurays(21)
    return movies


@router.post("/api/ignore-movie")
async def api_ignore_movie(
    request: IgnoreMovieRequest, repo: DatabaseRepository = Depends(get_repository)
) -> SuccessResponse:
    """Add movie to ignored list."""
    if not request.product_id:
        raise HTTPException(status_code=400, detail="Missing product_id")

    success = await repo.ignore_movie_by_product_id(request.product_id)

    if success:
        return SuccessResponse(message="Movie ignored")
    else:
        raise HTTPException(status_code=500, detail="Failed to ignore movie")


@router.get("/posters/{filename}")
async def serve_poster(filename: str) -> FileResponse:
    """Serve poster images from the posters directory."""
    poster_dir = CONFIG.get("poster_dir", "/app/data/posters")

    # Remove the /app prefix if running locally
    if not os.path.exists(poster_dir) and poster_dir.startswith("/app/"):
        local_poster_dir = poster_dir.replace("/app/", "./")
        if os.path.exists(local_poster_dir):
            poster_dir = local_poster_dir

    poster_path = os.path.join(poster_dir, filename)
    if not os.path.exists(poster_path):
        raise HTTPException(status_code=404, detail="Poster not found")

    return FileResponse(poster_path)
