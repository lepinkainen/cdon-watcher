"""Pydantic schemas for API requests only. Response models are now SQLModel variants."""

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
