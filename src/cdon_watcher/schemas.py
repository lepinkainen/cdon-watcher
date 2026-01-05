"""Pydantic schemas for API requests only. Response models are now SQLModel variants."""

from typing import Literal

from pydantic import BaseModel


# Request schemas
class WatchlistRequest(BaseModel):
    """Request model for adding to watchlist."""

    product_id: str
    target_price: float


class IgnoreMovieRequest(BaseModel):
    """Request model for ignoring a movie."""

    product_id: str


class SearchParams(BaseModel):
    """Search parameters."""

    q: str
    limit: int = 20


class ErrorResponse(BaseModel):
    """Error response model."""

    error: str
    detail: str | None = None


class SuccessResponse(BaseModel):
    """Success response model."""

    message: str


# TMDB Matching Queue schemas
class MatchConfirmRequest(BaseModel):
    """Request model for confirming a TMDB match."""

    movie_id: int
    tmdb_id: int | None  # None means "no match found"


class MatchSkipRequest(BaseModel):
    """Request model for skipping a match queue item."""

    movie_id: int


class ActionResponse(BaseModel):
    """Response model for watchlist/ignore actions."""

    status: Literal["confirmed", "queued", "error"]
    message: str | None = None
    tmdb_id: int | None = None
