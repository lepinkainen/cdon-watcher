"""Database repository using SQLModel for CDON Watcher."""

# Individual type: ignore comments added where needed with specific error codes

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ..models import (
    DealMovie,
    IgnoredMovie,
    Movie,
    MovieWithPricing,
    PriceAlert,
    PriceAlertWithTitle,
    PriceHistory,
    StatsData,
    Watchlist,
    WatchlistMovie,
)


class DatabaseRepository:
    """Repository for database operations using SQLModel."""

    def __init__(self, session: AsyncSession, enable_query_logging: bool = False):
        self.session = session
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.enable_query_logging = enable_query_logging

        if enable_query_logging:
            self.logger.setLevel(logging.DEBUG)

    @asynccontextmanager
    async def _handle_transaction(self, operation_name: str) -> Any:
        """Standard error handling with transaction management."""
        try:
            if self.enable_query_logging:
                self.logger.debug(f"Starting {operation_name}")
            yield
            await self.session.commit()
            if self.enable_query_logging:
                self.logger.debug(f"Successfully completed {operation_name}")
        except Exception as e:
            await self.session.rollback()
            self.logger.error(f"Failed {operation_name}: {e}")
            raise

    def _log_query(self, query_name: str, query: Any = None) -> None:
        """Log query execution for debugging."""
        if self.enable_query_logging:
            self.logger.debug(f"Executing {query_name}")
            if query:
                self.logger.debug(f"Query: {query}")

    def _current_price_subquery(self) -> Any:
        """Subquery for current price (latest price history entry)."""
        return (
            select(PriceHistory.price)
            .where(PriceHistory.movie_id == Movie.id)
            .order_by(PriceHistory.checked_at.desc())  # type: ignore
            .limit(1)
            .scalar_subquery()
        )

    def _previous_price_subquery(self) -> Any:
        """Subquery for previous price (second latest price history entry)."""
        return (
            select(PriceHistory.price)
            .where(PriceHistory.movie_id == Movie.id)
            .order_by(PriceHistory.id.desc())  # type: ignore
            .offset(1)
            .limit(1)
            .scalar_subquery()
        )

    def _lowest_price_subquery(self) -> Any:
        """Subquery for lowest price ever for a movie."""
        return (
            select(func.min(PriceHistory.price))
            .where(PriceHistory.movie_id == Movie.id)
            .scalar_subquery()
        )

    def _highest_price_subquery(self) -> Any:
        """Subquery for highest price ever for a movie."""
        return (
            select(func.max(PriceHistory.price))
            .where(PriceHistory.movie_id == Movie.id)
            .scalar_subquery()
        )

    async def get_stats(self) -> StatsData:
        """Get dashboard statistics."""
        # Get total movies
        result = await self.session.execute(select(func.count()).select_from(Movie))
        total_movies = result.scalar() or 0

        # Get price drops today
        today = datetime.now(UTC).date()
        result = await self.session.execute(
            select(func.count())
            .select_from(PriceAlert)
            .where(func.date(PriceAlert.created_at) == today)
        )
        price_drops_today = result.scalar() or 0

        # Get watchlist count
        result = await self.session.execute(select(func.count()).select_from(Watchlist))
        watchlist_count = result.scalar() or 0

        # Get last update
        result = await self.session.execute(
            select(Movie.last_updated).order_by(Movie.last_updated.desc()).limit(1)  # type: ignore
        )
        last_update = result.scalar()
        last_update_str = last_update.isoformat() if last_update else None  # type: ignore

        return StatsData(
            total_movies=total_movies,
            price_drops_today=price_drops_today,
            watchlist_count=watchlist_count,
            last_update=last_update_str,
        )

    async def get_deals(self, limit: int = 12) -> list[DealMovie]:
        """Get movies with biggest price drops."""
        current_price_sq = self._current_price_subquery()
        previous_price_sq = self._previous_price_subquery()
        lowest_price_sq = self._lowest_price_subquery()
        highest_price_sq = self._highest_price_subquery()

        # Main query with price drop filter
        query = (
            select(  # type: ignore
                Movie.id,
                Movie.product_id,
                Movie.title,
                Movie.format,
                Movie.url,
                Movie.image_url,
                Movie.tmdb_id,
                current_price_sq.label("current_price"),
                previous_price_sq.label("previous_price"),
                (previous_price_sq - current_price_sq).label("price_change"),
                lowest_price_sq.label("lowest_price"),
                highest_price_sq.label("highest_price"),
            )
            .where(
                and_(
                    current_price_sq.is_not(None),
                    previous_price_sq.is_not(None),
                    current_price_sq < previous_price_sq,
                )
            )
            .order_by((previous_price_sq - current_price_sq).asc())
            .limit(limit)
        )

        self._log_query("get_deals", query)
        result = await self.session.execute(query)

        return [DealMovie.model_validate(dict(row._mapping)) for row in result.all()]

    async def get_watchlist(self) -> list[WatchlistMovie]:
        """Get all watchlist items."""
        current_price_sq = self._current_price_subquery()
        lowest_price_sq = self._lowest_price_subquery()
        highest_price_sq = self._highest_price_subquery()

        query = select(  # type: ignore
            Movie.id,
            Movie.product_id,
            Movie.title,
            Movie.format,
            Movie.url,
            Movie.image_url,
            Movie.tmdb_id,
            Movie.content_type,
            Movie.first_seen,
            Movie.last_updated,
            Watchlist.target_price,
            current_price_sq.label("current_price"),
            lowest_price_sq.label("lowest_price"),
            highest_price_sq.label("highest_price"),
        ).join(Movie, Watchlist.movie_id == Movie.id)

        self._log_query("get_watchlist", query)
        result = await self.session.execute(query)

        return [WatchlistMovie.model_validate(dict(row._mapping)) for row in result.all()]

    async def add_to_watchlist(self, product_id: str, target_price: float) -> bool:
        """Add a movie to watchlist by product_id."""
        async with self._handle_transaction(f"add_to_watchlist({product_id})"):
            # Get movie by product_id
            result = await self.session.execute(select(Movie).where(Movie.product_id == product_id))
            movie = result.scalar_one_or_none()
            if not movie:
                return False

            # Check if already in watchlist
            existing_result = await self.session.execute(
                select(Watchlist).where(Watchlist.movie_id == movie.id)
            )
            existing_watchlist = existing_result.scalar_one_or_none()
            if existing_watchlist:
                # Update existing entry
                existing_watchlist.target_price = target_price
                existing_watchlist.created_at = datetime.utcnow()
            else:
                # Create new entry
                watchlist_item = Watchlist(
                    movie_id=movie.id,
                    product_id=product_id,
                    target_price=target_price,
                    created_at=datetime.utcnow(),
                )
                self.session.add(watchlist_item)

            return True

    async def remove_from_watchlist(self, product_id: str) -> bool:
        """Remove a movie from watchlist by product_id."""
        async with self._handle_transaction(f"remove_from_watchlist({product_id})"):
            result = await self.session.execute(
                select(Watchlist).where(Watchlist.product_id == product_id)
            )
            watchlist_item = result.scalar_one_or_none()
            if watchlist_item:
                await self.session.delete(watchlist_item)
            return True

    async def search_movies(self, query: str, limit: int = 20) -> list[MovieWithPricing]:
        """Search for movies by title."""
        if not query or not query.strip():
            return []

        current_price_sq = self._current_price_subquery()
        lowest_price_sq = self._lowest_price_subquery()
        highest_price_sq = self._highest_price_subquery()

        sql_query = (
            select(
                Movie.id,
                Movie.product_id,
                Movie.title,
                Movie.format,
                Movie.url,
                Movie.image_url,
                Movie.tmdb_id,
                Movie.content_type,
                Movie.first_seen,
                Movie.last_updated,
                current_price_sq.label("current_price"),
                lowest_price_sq.label("lowest_price"),
                highest_price_sq.label("highest_price"),
            )  # type: ignore[call-overload, misc]
            .where(Movie.title.ilike(f"%{query}%"))  # type: ignore[attr-defined]
            .order_by(Movie.title)
            .limit(limit)
        )

        self._log_query(f"search_movies(query='{query}')")
        result = await self.session.execute(sql_query)

        return [MovieWithPricing.model_validate(dict(row._mapping)) for row in result.all()]

    async def get_cheapest_blurays(self, limit: int = 21) -> list[MovieWithPricing]:
        """Get cheapest Blu-ray movies."""
        current_price_sq = self._current_price_subquery()
        lowest_price_sq = self._lowest_price_subquery()
        highest_price_sq = self._highest_price_subquery()

        # Subquery for ignored movies
        ignored_movies_sq = select(IgnoredMovie.movie_id)

        # Subquery for watchlisted movies
        watchlist_movies_sq = select(Watchlist.movie_id)

        query = (
            select(
                Movie.id,
                Movie.product_id,
                Movie.title,
                Movie.format,
                Movie.url,
                Movie.image_url,
                Movie.tmdb_id,
                Movie.content_type,
                Movie.first_seen,
                Movie.last_updated,
                current_price_sq.label("current_price"),
                lowest_price_sq.label("lowest_price"),
                highest_price_sq.label("highest_price"),
            )  # type: ignore[call-overload, misc]
            .where(
                and_(
                    Movie.format.ilike("%Blu-ray%"),  # type: ignore[union-attr]
                    ~Movie.format.ilike("%4K%"),  # type: ignore[union-attr]
                    Movie.id.not_in(ignored_movies_sq),  # type: ignore[union-attr]
                    Movie.id.not_in(watchlist_movies_sq),  # type: ignore[union-attr]
                    current_price_sq.is_not(None),
                )
            )
            .order_by(current_price_sq.asc())
            .limit(limit)
        )

        self._log_query("get_cheapest_blurays", query)
        result = await self.session.execute(query)

        return [MovieWithPricing.model_validate(dict(row._mapping)) for row in result.all()]

    async def get_cheapest_4k_blurays(self, limit: int = 21) -> list[MovieWithPricing]:
        """Get cheapest 4K Blu-ray movies."""
        current_price_sq = self._current_price_subquery()
        lowest_price_sq = self._lowest_price_subquery()
        highest_price_sq = self._highest_price_subquery()

        # Subquery for ignored movies
        ignored_movies_sq = select(IgnoredMovie.movie_id)

        # Subquery for watchlisted movies
        watchlist_movies_sq = select(Watchlist.movie_id)

        query = (
            select(
                Movie.id,
                Movie.product_id,
                Movie.title,
                Movie.format,
                Movie.url,
                Movie.image_url,
                Movie.tmdb_id,
                Movie.content_type,
                Movie.first_seen,
                Movie.last_updated,
                current_price_sq.label("current_price"),
                lowest_price_sq.label("lowest_price"),
                highest_price_sq.label("highest_price"),
            )  # type: ignore[call-overload, misc]
            .where(
                and_(
                    Movie.format.ilike("%4K%"),  # type: ignore[union-attr]
                    Movie.id.not_in(ignored_movies_sq),  # type: ignore[union-attr]
                    Movie.id.not_in(watchlist_movies_sq),  # type: ignore[union-attr]
                    current_price_sq.is_not(None),
                )
            )
            .order_by(current_price_sq.asc())
            .limit(limit)
        )

        self._log_query("get_cheapest_4k_blurays", query)
        result = await self.session.execute(query)

        return [MovieWithPricing.model_validate(dict(row._mapping)) for row in result.all()]

    async def ignore_movie_by_product_id(self, product_id: str) -> bool:
        """Add a movie to the ignored list by product_id."""
        async with self._handle_transaction(f"ignore_movie_by_product_id({product_id})"):
            # Get movie by product_id
            result = await self.session.execute(select(Movie).where(Movie.product_id == product_id))
            movie = result.scalar_one_or_none()
            if not movie:
                return False

            # Check if already ignored
            existing = await self.session.execute(
                select(IgnoredMovie).where(IgnoredMovie.movie_id == movie.id)
            )
            if not existing.scalar_one_or_none():
                ignored_movie = IgnoredMovie(
                    movie_id=movie.id,
                    product_id=product_id,
                    ignored_at=datetime.utcnow(),
                )
                self.session.add(ignored_movie)

            return True

    async def ignore_movie(self, movie_id: int) -> bool:
        """Add a movie to the ignored list by movie_id (legacy method)."""
        try:
            # Use session.get() for primary key lookup
            movie = await self.session.get(Movie, movie_id)
            if not movie:
                return False

            return await self.ignore_movie_by_product_id(movie.product_id)
        except Exception:
            return False

    async def get_price_alerts(self, limit: int = 10) -> list[PriceAlertWithTitle]:
        """Get unnotified price alerts."""
        query = (
            select(  # type: ignore
                PriceAlert.id,
                PriceAlert.movie_id,
                PriceAlert.product_id,
                PriceAlert.old_price,
                PriceAlert.new_price,
                PriceAlert.alert_type,
                PriceAlert.created_at,
                PriceAlert.notified,
                Movie.title.label("movie_title"),  # type: ignore[attr-defined]
            )
            .join(Movie, PriceAlert.movie_id == Movie.id)
            .where(not PriceAlert.notified)
            .order_by(PriceAlert.created_at.desc())  # type: ignore
            .limit(limit)
        )

        self._log_query("get_price_alerts", query)
        result = await self.session.execute(query)

        return [PriceAlertWithTitle.model_validate(dict(row._mapping)) for row in result.all()]
