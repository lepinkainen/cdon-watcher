"""Database repository using SQLModel for CDON Watcher."""

import json
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ..config import CONFIG
from ..models import (
    BoxSetWatchlist,
    BoxSetWatchlistItem,
    DealMovie,
    IgnoredMovie,
    MatchQueue,
    MatchQueueResponse,
    Movie,
    MovieWithPricing,
    PriceAlert,
    PriceAlertWithTitle,
    PriceHistory,
    StatsData,
    TMDBCandidate,
    TMDBMovie,
    TMDBMovieResponse,
    Watchlist,
    WatchlistItem,
    WatchlistMovie,
)
from ..tmdb_service import CONFIDENCE_AUTO_CONFIRM, TMDBCandidateData, TMDBService


class DatabaseRepository:
    """Repository for database operations using SQLModel."""

    def __init__(
        self,
        session: AsyncSession,
        enable_query_logging: bool = False,
        tmdb_service: TMDBService | None = None,
    ):
        self.session = session
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.enable_query_logging = enable_query_logging
        self.tmdb_service = tmdb_service

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

    def _ignored_tmdb_subquery(self) -> Any:
        """Subquery for ignored TMDB IDs."""
        return select(IgnoredMovie.tmdb_id)

    def _watchlist_tmdb_subquery(self) -> Any:
        """Subquery for watchlisted TMDB IDs."""
        return select(Watchlist.tmdb_id)

    def _box_set_watchlist_subquery(self) -> Any:
        """Subquery for watchlisted box set movie IDs."""
        return select(BoxSetWatchlist.movie_id)

    # ==================== Stats ====================

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

        # Get match queue count
        result = await self.session.execute(
            select(func.count()).select_from(MatchQueue).where(MatchQueue.skipped == False)  # noqa: E712
        )
        match_queue_count = result.scalar() or 0

        # Get box set watchlist count
        result = await self.session.execute(
            select(func.count()).select_from(BoxSetWatchlist)
        )
        box_set_watchlist_count = result.scalar() or 0

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
            box_set_watchlist_count=box_set_watchlist_count,
            match_queue_count=match_queue_count,
            last_update=last_update_str,
        )

    # ==================== TMDB Movie Cache ====================

    async def save_tmdb_movie(self, candidate: TMDBCandidateData) -> TMDBMovie:
        """Save or update TMDB movie metadata."""
        async with self._handle_transaction(f"save_tmdb_movie({candidate.tmdb_id})"):
            # Check if already exists
            existing = await self.session.get(TMDBMovie, candidate.tmdb_id)
            if existing:
                # Update existing
                existing.imdb_id = candidate.imdb_id
                existing.title = candidate.title
                existing.original_title = candidate.original_title
                existing.release_year = candidate.release_year
                existing.poster_path = candidate.poster_path
                existing.overview = candidate.overview
                existing.director = candidate.director
                existing.cast = ", ".join(candidate.cast) if candidate.cast else None
                existing.content_type = candidate.content_type
                return existing
            else:
                # Create new
                tmdb_movie = TMDBMovie(
                    tmdb_id=candidate.tmdb_id,
                    imdb_id=candidate.imdb_id,
                    title=candidate.title,
                    original_title=candidate.original_title,
                    release_year=candidate.release_year,
                    poster_path=candidate.poster_path,
                    overview=candidate.overview,
                    director=candidate.director,
                    cast=", ".join(candidate.cast) if candidate.cast else None,
                    content_type=candidate.content_type,
                    created_at=datetime.now(UTC),
                )
                self.session.add(tmdb_movie)
                return tmdb_movie

    async def get_tmdb_movie(self, tmdb_id: int) -> TMDBMovie | None:
        """Get TMDB movie by ID."""
        return await self.session.get(TMDBMovie, tmdb_id)

    # ==================== Movie <-> TMDB Linking ====================

    async def verify_movie_tmdb(self, movie_id: int, tmdb_id: int) -> bool:
        """Mark a movie's TMDB link as verified."""
        async with self._handle_transaction(f"verify_movie_tmdb({movie_id}, {tmdb_id})"):
            movie = await self.session.get(Movie, movie_id)
            if not movie:
                return False

            movie.tmdb_id = tmdb_id
            movie.tmdb_status = "verified"
            return True

    async def mark_movie_no_tmdb_match(self, movie_id: int) -> bool:
        """Mark a movie as having no TMDB match."""
        async with self._handle_transaction(f"mark_movie_no_tmdb_match({movie_id})"):
            movie = await self.session.get(Movie, movie_id)
            if not movie:
                return False

            movie.tmdb_id = None
            movie.tmdb_status = "no_match"
            return True

    async def get_movies_by_tmdb_id(self, tmdb_id: int) -> list[MovieWithPricing]:
        """Get all movie versions (formats) sharing a TMDB ID."""
        current_price_sq = self._current_price_subquery()
        lowest_price_sq = self._lowest_price_subquery()
        highest_price_sq = self._highest_price_subquery()

        query = (
            select(
                Movie.id,
                Movie.product_id,
                Movie.title,
                Movie.format,
                Movie.url,
                Movie.image_url,
                Movie.production_year,
                Movie.tmdb_id,
                Movie.tmdb_status,
                Movie.content_type,
                Movie.is_box_set,
                Movie.first_seen,
                Movie.last_updated,
                current_price_sq.label("current_price"),
                lowest_price_sq.label("lowest_price"),
                highest_price_sq.label("highest_price"),
            )  # type: ignore[call-overload, misc]
            .where(Movie.tmdb_id == tmdb_id)
            .order_by(current_price_sq.asc().nulls_last())
        )

        result = await self.session.execute(query)
        return [MovieWithPricing.model_validate(dict(row._mapping)) for row in result.all()]

    async def get_movie_by_product_id(self, product_id: str) -> Movie | None:
        """Get movie by product_id."""
        result = await self.session.execute(select(Movie).where(Movie.product_id == product_id))
        return result.scalar_one_or_none()

    async def get_movie_with_pricing(self, movie_id: int) -> MovieWithPricing | None:
        """Get movie with pricing info by ID."""
        current_price_sq = self._current_price_subquery()
        lowest_price_sq = self._lowest_price_subquery()
        highest_price_sq = self._highest_price_subquery()

        query = select(
            Movie.id,
            Movie.product_id,
            Movie.title,
            Movie.format,
            Movie.url,
            Movie.image_url,
            Movie.production_year,
            Movie.tmdb_id,
            Movie.tmdb_status,
            Movie.content_type,
            Movie.is_box_set,
            Movie.first_seen,
            Movie.last_updated,
            current_price_sq.label("current_price"),
            lowest_price_sq.label("lowest_price"),
            highest_price_sq.label("highest_price"),
        ).where(Movie.id == movie_id)  # type: ignore[call-overload, misc]

        result = await self.session.execute(query)
        row = result.one_or_none()
        if row:
            return MovieWithPricing.model_validate(dict(row._mapping))
        return None

    # ==================== Watchlist (TMDB-based) ====================

    async def add_to_watchlist(self, tmdb_id: int, target_price: float) -> bool:
        """Add movie to watchlist by TMDB ID."""
        async with self._handle_transaction(f"add_to_watchlist({tmdb_id})"):
            # Check if TMDB movie exists
            tmdb_movie = await self.session.get(TMDBMovie, tmdb_id)
            if not tmdb_movie:
                return False

            # Check if already in watchlist
            result = await self.session.execute(
                select(Watchlist).where(Watchlist.tmdb_id == tmdb_id)
            )
            existing = result.scalar_one_or_none()

            if existing:
                # Update existing
                existing.target_price = target_price
                existing.created_at = datetime.now(UTC)
            else:
                # Create new
                watchlist_item = Watchlist(
                    tmdb_id=tmdb_id,
                    target_price=target_price,
                    created_at=datetime.now(UTC),
                )
                self.session.add(watchlist_item)

            return True

    async def remove_from_watchlist(self, tmdb_id: int) -> bool:
        """Remove from watchlist by TMDB ID."""
        async with self._handle_transaction(f"remove_from_watchlist({tmdb_id})"):
            result = await self.session.execute(
                select(Watchlist).where(Watchlist.tmdb_id == tmdb_id)
            )
            watchlist_item = result.scalar_one_or_none()
            if watchlist_item:
                await self.session.delete(watchlist_item)
            return True

    async def get_watchlist(self) -> list[WatchlistItem]:
        """Get all watchlist items with TMDB info and all format versions."""
        # Get all watchlist entries with TMDB movie info
        query = (
            select(Watchlist, TMDBMovie)
            .join(TMDBMovie, Watchlist.tmdb_id == TMDBMovie.tmdb_id)  # type: ignore[arg-type]
            .order_by(Watchlist.created_at.desc())  # type: ignore[attr-defined]
        )

        result = await self.session.execute(query)
        rows = result.all()

        watchlist_items: list[WatchlistItem] = []
        for watchlist, tmdb_movie in rows:
            # Get all movie versions for this TMDB ID
            versions = await self.get_movies_by_tmdb_id(tmdb_movie.tmdb_id)

            tmdb_response = TMDBMovieResponse(
                tmdb_id=tmdb_movie.tmdb_id,
                imdb_id=tmdb_movie.imdb_id,
                title=tmdb_movie.title,
                original_title=tmdb_movie.original_title,
                release_year=tmdb_movie.release_year,
                poster_path=tmdb_movie.poster_path,
                overview=tmdb_movie.overview,
                director=tmdb_movie.director,
                cast=tmdb_movie.cast,
                content_type=tmdb_movie.content_type,
            )

            watchlist_items.append(
                WatchlistItem(
                    tmdb_movie=tmdb_response,
                    target_price=watchlist.target_price,
                    created_at=watchlist.created_at,
                    versions=versions,
                )
            )

        return watchlist_items

    async def get_watchlist_legacy(self) -> list[WatchlistMovie]:
        """Get watchlist in legacy format (for backward compatibility)."""
        watchlist_items = await self.get_watchlist()
        legacy_items: list[WatchlistMovie] = []

        for item in watchlist_items:
            for version in item.versions:
                legacy_items.append(
                    WatchlistMovie(
                        id=version.id,
                        product_id=version.product_id,
                        title=version.title,
                        format=version.format,
                        url=version.url,
                        image_url=version.image_url,
                        production_year=version.production_year,
                        tmdb_id=version.tmdb_id,
                        content_type=version.content_type,
                        first_seen=version.first_seen,
                        last_updated=version.last_updated,
                        target_price=item.target_price,
                        current_price=version.current_price,
                        lowest_price=version.lowest_price,
                        highest_price=version.highest_price,
                    )
                )

        return legacy_items

    async def is_watchlisted(self, tmdb_id: int) -> bool:
        """Check if a TMDB ID is in watchlist."""
        result = await self.session.execute(
            select(func.count()).select_from(Watchlist).where(Watchlist.tmdb_id == tmdb_id)
        )
        count = result.scalar() or 0
        return count > 0

    # ==================== Ignored Movies (TMDB-based) ====================

    async def ignore_movie(self, tmdb_id: int) -> bool:
        """Ignore all versions of a movie by TMDB ID."""
        async with self._handle_transaction(f"ignore_movie({tmdb_id})"):
            # Check if TMDB movie exists
            tmdb_movie = await self.session.get(TMDBMovie, tmdb_id)
            if not tmdb_movie:
                return False

            # Check if already ignored
            result = await self.session.execute(
                select(IgnoredMovie).where(IgnoredMovie.tmdb_id == tmdb_id)
            )
            existing = result.scalar_one_or_none()

            if not existing:
                ignored = IgnoredMovie(
                    tmdb_id=tmdb_id,
                    ignored_at=datetime.now(UTC),
                )
                self.session.add(ignored)

            return True

    async def unignore_movie(self, tmdb_id: int) -> bool:
        """Unignore a movie by TMDB ID."""
        async with self._handle_transaction(f"unignore_movie({tmdb_id})"):
            result = await self.session.execute(
                select(IgnoredMovie).where(IgnoredMovie.tmdb_id == tmdb_id)
            )
            ignored = result.scalar_one_or_none()
            if ignored:
                await self.session.delete(ignored)
            return True

    async def is_ignored(self, tmdb_id: int) -> bool:
        """Check if a TMDB ID is ignored."""
        result = await self.session.execute(
            select(func.count()).select_from(IgnoredMovie).where(IgnoredMovie.tmdb_id == tmdb_id)
        )
        count = result.scalar() or 0
        return count > 0

    # ==================== Match Queue ====================

    async def add_to_match_queue(
        self,
        movie_id: int,
        action: str,
        target_price: float | None = None,
        candidate_tmdb_ids: list[int] | None = None,
    ) -> bool:
        """Add a movie to the match queue."""
        async with self._handle_transaction(f"add_to_match_queue({movie_id})"):
            # Check if already in queue
            result = await self.session.execute(
                select(MatchQueue).where(MatchQueue.movie_id == movie_id)
            )
            existing = result.scalar_one_or_none()

            candidates_json = json.dumps(candidate_tmdb_ids) if candidate_tmdb_ids else None

            if existing:
                existing.action = action
                existing.target_price = target_price
                existing.candidate_tmdb_ids = candidates_json
                existing.skipped = False
                existing.created_at = datetime.now(UTC)
            else:
                queue_item = MatchQueue(
                    movie_id=movie_id,
                    action=action,
                    target_price=target_price,
                    candidate_tmdb_ids=candidates_json,
                    skipped=False,
                    created_at=datetime.now(UTC),
                )
                self.session.add(queue_item)

            return True

    async def remove_from_match_queue(self, movie_id: int) -> bool:
        """Remove a movie from the match queue."""
        async with self._handle_transaction(f"remove_from_match_queue({movie_id})"):
            result = await self.session.execute(
                select(MatchQueue).where(MatchQueue.movie_id == movie_id)
            )
            queue_item = result.scalar_one_or_none()
            if queue_item:
                await self.session.delete(queue_item)
            return True

    async def skip_match_queue_item(self, movie_id: int) -> bool:
        """Mark a match queue item as skipped."""
        async with self._handle_transaction(f"skip_match_queue_item({movie_id})"):
            result = await self.session.execute(
                select(MatchQueue).where(MatchQueue.movie_id == movie_id)
            )
            queue_item = result.scalar_one_or_none()
            if queue_item:
                queue_item.skipped = True
            return True

    async def get_match_queue(self, offset: int = 0, include_skipped: bool = False) -> MatchQueueResponse:
        """Get match queue items with pagination."""
        # Count total
        count_query = select(func.count()).select_from(MatchQueue)
        if not include_skipped:
            count_query = count_query.where(MatchQueue.skipped == False)  # noqa: E712
        result = await self.session.execute(count_query)
        total = result.scalar() or 0

        if total == 0:
            return MatchQueueResponse(total=0, current_index=0, movie=None, candidates=[])

        # Get queue item at offset
        query = select(MatchQueue).order_by(MatchQueue.created_at.asc())  # type: ignore[attr-defined]
        if not include_skipped:
            query = query.where(MatchQueue.skipped == False)  # noqa: E712
        query = query.offset(offset).limit(1)

        result = await self.session.execute(query)
        queue_item = result.scalar_one_or_none()

        if not queue_item:
            return MatchQueueResponse(total=total, current_index=offset, movie=None, candidates=[])

        # Get movie with pricing
        movie = await self.get_movie_with_pricing(queue_item.movie_id)  # type: ignore[attr-defined]
        if not movie:
            return MatchQueueResponse(total=total, current_index=offset, movie=None, candidates=[])

        # Get candidates from TMDB service if available
        candidates: list[TMDBCandidate] = []
        if self.tmdb_service and movie.title:
            candidate_data = self.tmdb_service.search_candidates(
                movie.title, movie.production_year, limit=5
            )
            candidates = [
                TMDBCandidate(
                    tmdb_id=c.tmdb_id,
                    imdb_id=c.imdb_id,
                    title=c.title,
                    original_title=c.original_title,
                    release_year=c.release_year,
                    poster_url=self.tmdb_service.get_poster_url(c.poster_path),
                    overview=c.overview,
                    director=c.director,
                    cast=c.cast,
                    popularity=c.popularity,
                    content_type=c.content_type,
                    confidence_score=c.confidence_score,
                )
                for c in candidate_data
            ]

        return MatchQueueResponse(
            total=total,
            current_index=offset,
            movie=movie,
            candidates=candidates,
            queue_id=queue_item.id,  # type: ignore[attr-defined]
        )

    async def get_match_queue_item(self, queue_id: int) -> MatchQueue | None:
        """Get a specific match queue item."""
        return await self.session.get(MatchQueue, queue_id)

    async def confirm_match(
        self, movie_id: int, tmdb_id: int | None, action: str, target_price: float | None = None
    ) -> bool:
        """Confirm TMDB match and execute the action."""
        async with self._handle_transaction(f"confirm_match({movie_id}, {tmdb_id})"):
            # Update movie TMDB link
            if tmdb_id:
                await self.verify_movie_tmdb(movie_id, tmdb_id)

                # Execute action
                if action == "watchlist" and target_price is not None:
                    await self.add_to_watchlist(tmdb_id, target_price)
                elif action == "ignore":
                    await self.ignore_movie(tmdb_id)
            else:
                await self.mark_movie_no_tmdb_match(movie_id)

            # Remove from queue
            await self.remove_from_match_queue(movie_id)

            return True

    # ==================== Deals ====================

    async def get_deals(self, limit: int = 12) -> list[DealMovie]:
        """Get movies with biggest price drops."""
        current_price_sq = self._current_price_subquery()
        previous_price_sq = self._previous_price_subquery()
        lowest_price_sq = self._lowest_price_subquery()
        highest_price_sq = self._highest_price_subquery()
        ignored_tmdb_sq = self._ignored_tmdb_subquery()

        # Main query with price drop filter and minimum deal difference
        min_deal_diff = CONFIG["min_deal_diff"]
        query = (
            select(  # type: ignore
                Movie.id,
                Movie.product_id,
                Movie.title,
                Movie.format,
                Movie.url,
                Movie.image_url,
                Movie.production_year,
                Movie.tmdb_id,
                current_price_sq.label("current_price"),
                previous_price_sq.label("previous_price"),
                (previous_price_sq - current_price_sq).label("price_change"),
                lowest_price_sq.label("lowest_price"),
                highest_price_sq.label("highest_price"),
            )
            .where(
                and_(
                    Movie.available == True,  # type: ignore[arg-type]  # noqa: E712
                    current_price_sq.is_not(None),
                    previous_price_sq.is_not(None),
                    current_price_sq < previous_price_sq,
                    (previous_price_sq - current_price_sq) >= min_deal_diff,
                    # Exclude ignored movies by TMDB ID
                    or_(
                        Movie.tmdb_id.is_(None),  # type: ignore[union-attr]
                        Movie.tmdb_id.not_in(ignored_tmdb_sq),  # type: ignore[union-attr]
                    ),
                )
            )
            .order_by((previous_price_sq - current_price_sq).desc())
            .limit(limit)
        )

        self._log_query("get_deals", query)
        result = await self.session.execute(query)

        return [DealMovie.model_validate(dict(row._mapping)) for row in result.all()]

    # ==================== Search ====================

    async def search_movies(
        self, query: str, limit: int = 20, max_price: float | None = None, category: str = "all"
    ) -> list[MovieWithPricing]:
        """Search for movies by title with optional price and category filtering."""
        # Allow empty queries if we have filters
        has_filters = max_price is not None or category != "all"
        if not has_filters and (not query or not query.strip()):
            return []

        current_price_sq = self._current_price_subquery()
        lowest_price_sq = self._lowest_price_subquery()
        highest_price_sq = self._highest_price_subquery()
        ignored_tmdb_sq = self._ignored_tmdb_subquery()

        # Start with base query
        sql_query = select(
            Movie.id,
            Movie.product_id,
            Movie.title,
            Movie.format,
            Movie.url,
            Movie.image_url,
            Movie.production_year,
            Movie.tmdb_id,
            Movie.tmdb_status,
            Movie.content_type,
            Movie.is_box_set,
            Movie.first_seen,
            Movie.last_updated,
            current_price_sq.label("current_price"),
            lowest_price_sq.label("lowest_price"),
            highest_price_sq.label("highest_price"),
        )  # type: ignore[call-overload, misc]

        # Build WHERE conditions
        conditions = []

        # Exclude ignored movies
        conditions.append(
            or_(
                Movie.tmdb_id.is_(None),  # type: ignore[union-attr]
                Movie.tmdb_id.not_in(ignored_tmdb_sq),  # type: ignore[union-attr]
            )
        )

        # Add title search only if query is provided
        if query and query.strip():
            conditions.append(Movie.title.ilike(f"%{query}%"))  # type: ignore[attr-defined]

        # Add price filtering
        if max_price is not None:
            conditions.append(current_price_sq <= max_price)
            conditions.append(current_price_sq.is_not(None))

        # Add category filtering
        if category == "bluray":
            conditions.extend(
                [
                    Movie.format.ilike("%Blu-ray%"),  # type: ignore[union-attr]
                    ~Movie.format.ilike("%4K%"),  # type: ignore[union-attr]
                ]
            )
        elif category == "4k":
            conditions.append(Movie.format.ilike("%4K%"))  # type: ignore[union-attr]

        # Apply conditions if any exist
        if conditions:
            sql_query = sql_query.where(and_(*conditions))

        # Always order by price (lowest to highest), with NULL prices last
        sql_query = sql_query.order_by(current_price_sq.asc().nulls_last())

        sql_query = sql_query.limit(limit)

        self._log_query(
            f"search_movies(query='{query}', max_price={max_price}, category='{category}')"
        )
        result = await self.session.execute(sql_query)

        return [MovieWithPricing.model_validate(dict(row._mapping)) for row in result.all()]

    # ==================== Cheapest Movies ====================

    async def get_cheapest_blurays(self, limit: int = 21) -> list[MovieWithPricing]:
        """Get cheapest Blu-ray movies."""
        current_price_sq = self._current_price_subquery()
        lowest_price_sq = self._lowest_price_subquery()
        highest_price_sq = self._highest_price_subquery()
        ignored_tmdb_sq = self._ignored_tmdb_subquery()
        watchlist_tmdb_sq = self._watchlist_tmdb_subquery()

        query = (
            select(
                Movie.id,
                Movie.product_id,
                Movie.title,
                Movie.format,
                Movie.url,
                Movie.image_url,
                Movie.production_year,
                Movie.tmdb_id,
                Movie.tmdb_status,
                Movie.content_type,
                Movie.is_box_set,
                Movie.first_seen,
                Movie.last_updated,
                current_price_sq.label("current_price"),
                lowest_price_sq.label("lowest_price"),
                highest_price_sq.label("highest_price"),
            )  # type: ignore[call-overload, misc]
            .where(
                and_(
                    Movie.available == True,  # type: ignore[arg-type]  # noqa: E712
                    Movie.is_box_set == False,  # type: ignore[arg-type]  # noqa: E712
                    Movie.format.ilike("%Blu-ray%"),  # type: ignore[union-attr]
                    ~Movie.format.ilike("%4K%"),  # type: ignore[union-attr]
                    # Exclude ignored movies by TMDB ID
                    or_(
                        Movie.tmdb_id.is_(None),  # type: ignore[union-attr]
                        Movie.tmdb_id.not_in(ignored_tmdb_sq),  # type: ignore[union-attr]
                    ),
                    # Exclude watchlisted movies by TMDB ID
                    or_(
                        Movie.tmdb_id.is_(None),  # type: ignore[union-attr]
                        Movie.tmdb_id.not_in(watchlist_tmdb_sq),  # type: ignore[union-attr]
                    ),
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
        ignored_tmdb_sq = self._ignored_tmdb_subquery()
        watchlist_tmdb_sq = self._watchlist_tmdb_subquery()

        query = (
            select(
                Movie.id,
                Movie.product_id,
                Movie.title,
                Movie.format,
                Movie.url,
                Movie.image_url,
                Movie.production_year,
                Movie.tmdb_id,
                Movie.tmdb_status,
                Movie.content_type,
                Movie.is_box_set,
                Movie.first_seen,
                Movie.last_updated,
                current_price_sq.label("current_price"),
                lowest_price_sq.label("lowest_price"),
                highest_price_sq.label("highest_price"),
            )  # type: ignore[call-overload, misc]
            .where(
                and_(
                    Movie.available == True,  # type: ignore[arg-type]  # noqa: E712
                    Movie.is_box_set == False,  # type: ignore[arg-type]  # noqa: E712
                    Movie.format.ilike("%4K%"),  # type: ignore[union-attr]
                    # Exclude ignored movies by TMDB ID
                    or_(
                        Movie.tmdb_id.is_(None),  # type: ignore[union-attr]
                        Movie.tmdb_id.not_in(ignored_tmdb_sq),  # type: ignore[union-attr]
                    ),
                    # Exclude watchlisted movies by TMDB ID
                    or_(
                        Movie.tmdb_id.is_(None),  # type: ignore[union-attr]
                        Movie.tmdb_id.not_in(watchlist_tmdb_sq),  # type: ignore[union-attr]
                    ),
                    current_price_sq.is_not(None),
                )
            )
            .order_by(current_price_sq.asc())
            .limit(limit)
        )

        self._log_query("get_cheapest_4k_blurays", query)
        result = await self.session.execute(query)

        return [MovieWithPricing.model_validate(dict(row._mapping)) for row in result.all()]

    # ==================== Price Alerts ====================

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

    # ==================== Initiate Action (with auto-confirm logic) ====================

    async def initiate_watchlist_action(
        self, product_id: str, target_price: float
    ) -> dict[str, Any]:
        """
        Initiate adding a movie to watchlist.
        Returns: { "status": "confirmed" | "queued", "tmdb_id": int | None, "queue_id": int | None }
        """
        movie = await self.get_movie_by_product_id(product_id)
        if not movie:
            return {"status": "error", "message": "Movie not found"}

        # Box sets: bypass TMDB, add directly to box set watchlist
        if movie.is_box_set:
            await self.add_box_set_to_watchlist(movie.id, target_price)  # type: ignore[arg-type]
            return {"status": "confirmed", "movie_id": movie.id, "is_box_set": True}

        # If movie already has verified TMDB match
        if movie.tmdb_status == "verified" and movie.tmdb_id:
            # Ensure TMDBMovie exists
            tmdb_movie = await self.get_tmdb_movie(movie.tmdb_id)
            if tmdb_movie:
                await self.add_to_watchlist(movie.tmdb_id, target_price)
                return {"status": "confirmed", "tmdb_id": movie.tmdb_id}

        # Search for candidates
        if self.tmdb_service:
            candidates = self.tmdb_service.search_candidates(
                movie.title, movie.production_year, limit=5
            )

            # If top candidate has 95%+ confidence, auto-confirm
            if candidates and candidates[0].confidence_score >= CONFIDENCE_AUTO_CONFIRM:
                top = candidates[0]
                # Save TMDB movie
                await self.save_tmdb_movie(top)
                await self.verify_movie_tmdb(movie.id, top.tmdb_id)  # type: ignore[arg-type]
                await self.add_to_watchlist(top.tmdb_id, target_price)
                return {"status": "confirmed", "tmdb_id": top.tmdb_id}

            # Otherwise, add to queue
            candidate_ids = [c.tmdb_id for c in candidates]
            await self.add_to_match_queue(movie.id, "watchlist", target_price, candidate_ids)  # type: ignore[arg-type]
            return {"status": "queued", "message": "Added to matching queue"}

        # No TMDB service, add to queue anyway
        await self.add_to_match_queue(movie.id, "watchlist", target_price)  # type: ignore[arg-type]
        return {"status": "queued", "message": "Added to matching queue"}

    async def initiate_ignore_action(self, product_id: str) -> dict[str, Any]:
        """
        Initiate ignoring a movie.
        Returns: { "status": "confirmed" | "queued", "tmdb_id": int | None }
        """
        movie = await self.get_movie_by_product_id(product_id)
        if not movie:
            return {"status": "error", "message": "Movie not found"}

        # If movie already has verified TMDB match
        if movie.tmdb_status == "verified" and movie.tmdb_id:
            tmdb_movie = await self.get_tmdb_movie(movie.tmdb_id)
            if tmdb_movie:
                await self.ignore_movie(movie.tmdb_id)
                return {"status": "confirmed", "tmdb_id": movie.tmdb_id}

        # Search for candidates
        if self.tmdb_service:
            candidates = self.tmdb_service.search_candidates(
                movie.title, movie.production_year, limit=5
            )

            # If top candidate has 95%+ confidence, auto-confirm
            if candidates and candidates[0].confidence_score >= CONFIDENCE_AUTO_CONFIRM:
                top = candidates[0]
                await self.save_tmdb_movie(top)
                await self.verify_movie_tmdb(movie.id, top.tmdb_id)  # type: ignore[arg-type]
                await self.ignore_movie(top.tmdb_id)
                return {"status": "confirmed", "tmdb_id": top.tmdb_id}

            # Otherwise, add to queue
            candidate_ids = [c.tmdb_id for c in candidates]
            await self.add_to_match_queue(movie.id, "ignore", None, candidate_ids)  # type: ignore[arg-type]
            return {"status": "queued", "message": "Added to matching queue"}

        # No TMDB service, add to queue anyway
        await self.add_to_match_queue(movie.id, "ignore")  # type: ignore[arg-type]
        return {"status": "queued", "message": "Added to matching queue"}

    # ==================== Box Set Watchlist ====================

    async def add_box_set_to_watchlist(self, movie_id: int, target_price: float) -> bool:
        """Add box set to watchlist by movie_id (no TMDB needed)."""
        async with self._handle_transaction(f"add_box_set_to_watchlist({movie_id})"):
            # Verify it's a box set
            movie = await self.session.get(Movie, movie_id)
            if not movie or not movie.is_box_set:
                return False

            # Check if already in watchlist
            result = await self.session.execute(
                select(BoxSetWatchlist).where(BoxSetWatchlist.movie_id == movie_id)
            )
            existing = result.scalar_one_or_none()

            if existing:
                existing.target_price = target_price
                existing.created_at = datetime.now(UTC)
            else:
                watchlist_item = BoxSetWatchlist(
                    movie_id=movie_id,
                    target_price=target_price,
                    created_at=datetime.now(UTC),
                )
                self.session.add(watchlist_item)

            return True

    async def remove_box_set_from_watchlist(self, movie_id: int) -> bool:
        """Remove box set from watchlist."""
        async with self._handle_transaction(f"remove_box_set_from_watchlist({movie_id})"):
            result = await self.session.execute(
                select(BoxSetWatchlist).where(BoxSetWatchlist.movie_id == movie_id)
            )
            item = result.scalar_one_or_none()
            if item:
                await self.session.delete(item)
            return True

    async def get_box_set_watchlist(self) -> list[BoxSetWatchlistItem]:
        """Get all box set watchlist items."""
        current_price_sq = self._current_price_subquery()
        lowest_price_sq = self._lowest_price_subquery()
        highest_price_sq = self._highest_price_subquery()

        query = (
            select(
                BoxSetWatchlist.target_price,
                BoxSetWatchlist.created_at.label("watchlist_created_at"),  # type: ignore[attr-defined]
                Movie.id,
                Movie.product_id,
                Movie.title,
                Movie.format,
                Movie.url,
                Movie.image_url,
                Movie.production_year,
                Movie.tmdb_id,
                Movie.tmdb_status,
                Movie.content_type,
                Movie.is_box_set,
                Movie.first_seen,
                Movie.last_updated,
                current_price_sq.label("current_price"),
                lowest_price_sq.label("lowest_price"),
                highest_price_sq.label("highest_price"),
            )  # type: ignore[call-overload, misc]
            .join(Movie, BoxSetWatchlist.movie_id == Movie.id)
            .order_by(BoxSetWatchlist.created_at.desc())  # type: ignore[attr-defined]
        )

        result = await self.session.execute(query)
        items: list[BoxSetWatchlistItem] = []
        for row in result.all():
            row_dict = dict(row._mapping)
            movie = MovieWithPricing(
                id=row_dict["id"],
                product_id=row_dict["product_id"],
                title=row_dict["title"],
                format=row_dict["format"],
                url=row_dict["url"],
                image_url=row_dict["image_url"],
                production_year=row_dict["production_year"],
                tmdb_id=row_dict["tmdb_id"],
                tmdb_status=row_dict["tmdb_status"],
                content_type=row_dict["content_type"],
                is_box_set=row_dict["is_box_set"],
                first_seen=row_dict["first_seen"],
                last_updated=row_dict["last_updated"],
                current_price=row_dict["current_price"],
                lowest_price=row_dict["lowest_price"],
                highest_price=row_dict["highest_price"],
            )
            items.append(
                BoxSetWatchlistItem(
                    movie=movie,
                    target_price=row_dict["target_price"],
                    created_at=row_dict["watchlist_created_at"],
                )
            )
        return items

    async def get_box_sets(self, limit: int = 21) -> list[MovieWithPricing]:
        """Get available box sets ordered by price."""
        current_price_sq = self._current_price_subquery()
        lowest_price_sq = self._lowest_price_subquery()
        highest_price_sq = self._highest_price_subquery()
        box_set_watchlist_sq = self._box_set_watchlist_subquery()

        query = (
            select(
                Movie.id,
                Movie.product_id,
                Movie.title,
                Movie.format,
                Movie.url,
                Movie.image_url,
                Movie.production_year,
                Movie.tmdb_id,
                Movie.tmdb_status,
                Movie.content_type,
                Movie.is_box_set,
                Movie.first_seen,
                Movie.last_updated,
                current_price_sq.label("current_price"),
                lowest_price_sq.label("lowest_price"),
                highest_price_sq.label("highest_price"),
            )  # type: ignore[call-overload, misc]
            .where(
                and_(
                    Movie.available == True,  # type: ignore[arg-type]  # noqa: E712
                    Movie.is_box_set == True,  # type: ignore[arg-type]  # noqa: E712
                    # Exclude already watchlisted box sets
                    Movie.id.not_in(box_set_watchlist_sq),  # type: ignore[union-attr]
                    current_price_sq.is_not(None),
                )
            )
            .order_by(current_price_sq.asc())
            .limit(limit)
        )

        self._log_query("get_box_sets", query)
        result = await self.session.execute(query)

        return [MovieWithPricing.model_validate(dict(row._mapping)) for row in result.all()]

    async def is_box_set_watchlisted(self, movie_id: int) -> bool:
        """Check if a box set movie is in the watchlist."""
        result = await self.session.execute(
            select(func.count())
            .select_from(BoxSetWatchlist)
            .where(BoxSetWatchlist.movie_id == movie_id)
        )
        count = result.scalar() or 0
        return count > 0
