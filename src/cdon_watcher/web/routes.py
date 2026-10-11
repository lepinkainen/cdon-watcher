"""FastAPI routes for the web dashboard."""

import os

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import CONFIG
from ..database.connection import get_db_session
from ..database.repository import DatabaseRepository
from ..models import (
    BoxSetWatchlistItem,
    DealMovie,
    MatchQueueResponse,
    MovieWithPricing,
    PriceAlertWithTitle,
    StatsData,
    WatchlistItem,
    WatchlistMovie,
)
from ..schemas import (
    ActionResponse,
    IgnoreMovieRequest,
    MatchConfirmRequest,
    MatchSkipRequest,
    SuccessResponse,
    WatchlistRequest,
)
from ..tmdb_service import TMDBService

# Create router
router = APIRouter()

# Global TMDB service instance (lazy init)
_tmdb_service: TMDBService | None = None


def get_tmdb_service() -> TMDBService | None:
    """Get or create TMDB service instance."""
    global _tmdb_service
    if _tmdb_service is None:
        tmdb_api_key = CONFIG.get("tmdb_api_key")
        if tmdb_api_key:
            poster_dir = CONFIG.get("poster_dir", "./data/posters")
            _tmdb_service = TMDBService(tmdb_api_key, poster_dir)
    return _tmdb_service


# Dependency function for DatabaseRepository
async def get_repository(session: AsyncSession = Depends(get_db_session)) -> DatabaseRepository:
    """Get DatabaseRepository instance with TMDB service."""
    # Enable query logging in development mode (can be controlled via environment variable)
    enable_logging = CONFIG.get("debug", False) or CONFIG.get("enable_query_logging", False)
    tmdb_service = get_tmdb_service()
    return DatabaseRepository(
        session, enable_query_logging=enable_logging, tmdb_service=tmdb_service
    )


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


# ==================== Watchlist (TMDB-based) ====================


@router.get("/api/watchlist", response_model=list[WatchlistItem])
async def api_get_watchlist(
    repo: DatabaseRepository = Depends(get_repository),
) -> list[WatchlistItem]:
    """Get watchlist items with TMDB info and all format versions."""
    watchlist = await repo.get_watchlist()
    return watchlist


@router.get("/api/watchlist/legacy", response_model=list[WatchlistMovie])
async def api_get_watchlist_legacy(
    repo: DatabaseRepository = Depends(get_repository),
) -> list[WatchlistMovie]:
    """Get watchlist items in legacy format (flat list)."""
    watchlist = await repo.get_watchlist_legacy()
    return watchlist


@router.post("/api/watchlist", response_model=ActionResponse)
async def api_add_to_watchlist(
    request: WatchlistRequest, repo: DatabaseRepository = Depends(get_repository)
) -> ActionResponse:
    """Add item to watchlist. May queue for TMDB matching if no confident match."""
    if not request.target_price:
        raise HTTPException(status_code=400, detail="Missing target_price")

    if not request.product_id:
        raise HTTPException(status_code=400, detail="Missing product_id")

    result = await repo.initiate_watchlist_action(request.product_id, request.target_price)

    return ActionResponse(
        status=result.get("status", "error"),
        message=result.get("message"),
        tmdb_id=result.get("tmdb_id"),
    )


@router.delete("/api/watchlist/{tmdb_id}")
async def api_remove_from_watchlist(
    tmdb_id: int, repo: DatabaseRepository = Depends(get_repository)
) -> SuccessResponse:
    """Remove movie from watchlist by TMDB ID."""
    success = await repo.remove_from_watchlist(tmdb_id)

    if success:
        return SuccessResponse(message="Removed from watchlist")
    else:
        raise HTTPException(status_code=500, detail="Failed to remove from watchlist")


# ==================== Ignore Movies (TMDB-based) ====================


@router.post("/api/ignore-movie", response_model=ActionResponse)
async def api_ignore_movie(
    request: IgnoreMovieRequest, repo: DatabaseRepository = Depends(get_repository)
) -> ActionResponse:
    """Add movie to ignored list. May queue for TMDB matching if no confident match."""
    if not request.product_id:
        raise HTTPException(status_code=400, detail="Missing product_id")

    result = await repo.initiate_ignore_action(request.product_id)

    return ActionResponse(
        status=result.get("status", "error"),
        message=result.get("message"),
        tmdb_id=result.get("tmdb_id"),
    )


# ==================== Match Queue ====================


@router.get("/api/match/queue", response_model=MatchQueueResponse)
async def api_get_match_queue(
    offset: int = Query(0, ge=0, description="Queue offset"),
    include_skipped: bool = Query(False, description="Include skipped items"),
    repo: DatabaseRepository = Depends(get_repository),
) -> MatchQueueResponse:
    """Get match queue items with pagination."""
    return await repo.get_match_queue(offset, include_skipped)


@router.post("/api/match/confirm", response_model=SuccessResponse)
async def api_confirm_match(
    request: MatchConfirmRequest, repo: DatabaseRepository = Depends(get_repository)
) -> SuccessResponse:
    """Confirm TMDB match and execute the pending action."""
    # Get the queue item to find action and target_price
    queue_item = None
    match_queue = await repo.get_match_queue()
    if match_queue.movie and match_queue.movie.id == request.movie_id:
        queue_item = await repo.get_match_queue_item(match_queue.queue_id)  # type: ignore

    if not queue_item:
        raise HTTPException(status_code=404, detail="Queue item not found")

    # If tmdb_id is provided, save the TMDB movie first
    if request.tmdb_id and repo.tmdb_service:
        candidates = repo.tmdb_service.search_candidates(
            match_queue.movie.title if match_queue.movie else "",
            match_queue.movie.production_year if match_queue.movie else None,
            limit=5,
        )
        # Find the matching candidate
        for candidate in candidates:
            if candidate.tmdb_id == request.tmdb_id:
                await repo.save_tmdb_movie(candidate)
                break

    success = await repo.confirm_match(
        request.movie_id,
        request.tmdb_id,
        queue_item.action,
        queue_item.target_price,
    )

    if success:
        return SuccessResponse(message="Match confirmed")
    else:
        raise HTTPException(status_code=500, detail="Failed to confirm match")


@router.post("/api/match/skip", response_model=SuccessResponse)
async def api_skip_match(
    request: MatchSkipRequest, repo: DatabaseRepository = Depends(get_repository)
) -> SuccessResponse:
    """Skip a match queue item."""
    success = await repo.skip_match_queue_item(request.movie_id)

    if success:
        return SuccessResponse(message="Item skipped")
    else:
        raise HTTPException(status_code=500, detail="Failed to skip item")


# ==================== Search ====================


@router.get("/api/search", response_model=list[MovieWithPricing])
async def api_search(
    q: str = Query("", description="Search query"),
    max_price: float | None = Query(None, description="Maximum price filter"),
    category: str = Query("all", description="Category filter: all, bluray, or 4k"),
    repo: DatabaseRepository = Depends(get_repository),
) -> list[MovieWithPricing]:
    """Search for movies with optional price and category filtering."""
    movies = await repo.search_movies(q, 20, max_price, category)
    return movies


# ==================== Cheapest Movies ====================


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


# ==================== Box Sets ====================


@router.get("/api/box-sets", response_model=list[MovieWithPricing])
async def api_get_box_sets(
    repo: DatabaseRepository = Depends(get_repository),
) -> list[MovieWithPricing]:
    """Get available box sets."""
    box_sets = await repo.get_box_sets(21)
    return box_sets


@router.get("/api/box-sets/watchlist", response_model=list[BoxSetWatchlistItem])
async def api_get_box_set_watchlist(
    repo: DatabaseRepository = Depends(get_repository),
) -> list[BoxSetWatchlistItem]:
    """Get box set watchlist."""
    watchlist = await repo.get_box_set_watchlist()
    return watchlist


@router.delete("/api/box-sets/watchlist/{movie_id}")
async def api_remove_box_set_from_watchlist(
    movie_id: int, repo: DatabaseRepository = Depends(get_repository)
) -> SuccessResponse:
    """Remove box set from watchlist."""
    success = await repo.remove_box_set_from_watchlist(movie_id)
    if success:
        return SuccessResponse(message="Removed from box set watchlist")
    raise HTTPException(status_code=500, detail="Failed to remove")


# ==================== TMDB Versions ====================


@router.get("/api/tmdb/{tmdb_id}/versions", response_model=list[MovieWithPricing])
async def api_get_tmdb_versions(
    tmdb_id: int, repo: DatabaseRepository = Depends(get_repository)
) -> list[MovieWithPricing]:
    """Get all movie versions (formats) sharing a TMDB ID."""
    movies = await repo.get_movies_by_tmdb_id(tmdb_id)
    return movies


# ==================== Static Files ====================


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
