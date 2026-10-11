"""Unit tests for watchlist exclusion in cheapest Blu-ray queries."""

import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cdon_watcher.database.repository import DatabaseRepository
from cdon_watcher.models import Movie, PriceHistory, TMDBMovie, Watchlist


@pytest.fixture
def temp_db_path():
    """Provide a temporary database path for tests."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_file:
        temp_path = tmp_file.name

    yield temp_path

    # Clean up
    temp_file_path = Path(temp_path)
    if temp_file_path.exists():
        temp_file_path.unlink()


@pytest.fixture
async def test_db_session(temp_db_path, monkeypatch):
    """Create test database session with schema and test data."""
    # Mock config to use our test database
    from cdon_watcher.config import CONFIG

    monkeypatch.setitem(CONFIG, "db_path", temp_db_path)

    # Create a new engine and session factory for our isolated test database
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlmodel import SQLModel

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{temp_db_path}",
        echo=False,
        future=True,
    )

    # Initialize database schema
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    # Create session factory for our test engine
    test_session_local = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    # Create session for tests
    async with test_session_local() as session:
        # Add test data
        await _populate_test_data(session)
        yield session

    await engine.dispose()


async def _populate_test_data(session):
    """Populate database with test data for watchlist exclusion tests."""
    now = datetime.now(UTC)

    # Create TMDB movies first (for linking to watchlist)
    tmdb_movies = [
        TMDBMovie(tmdb_id=1001, title="Test Movie 1", release_year=2020, created_at=now),
        TMDBMovie(tmdb_id=1003, title="Test Movie 3", release_year=2021, created_at=now),
    ]

    for tmdb_movie in tmdb_movies:
        session.add(tmdb_movie)

    await session.commit()

    # Create test movies with TMDB links
    movies = [
        Movie(
            product_id="movie-1",
            title="Test Movie 1",
            format="Blu-ray",
            url="https://cdon.fi/movie-1",
            tmdb_id=1001,  # Linked to TMDB
            tmdb_status="verified",
            first_seen=now,
            last_updated=now,
        ),
        Movie(
            product_id="movie-2",
            title="Test Movie 2",
            format="Blu-ray",
            url="https://cdon.fi/movie-2",
            tmdb_id=None,  # Not linked - won't be excluded by watchlist
            first_seen=now,
            last_updated=now,
        ),
        Movie(
            product_id="movie-3",
            title="Test Movie 3",
            format="4K Blu-ray",
            url="https://cdon.fi/movie-3",
            tmdb_id=1003,  # Linked to TMDB
            tmdb_status="verified",
            first_seen=now,
            last_updated=now,
        ),
        Movie(
            product_id="movie-4",
            title="Test Movie 4",
            format="4K Blu-ray",
            url="https://cdon.fi/movie-4",
            tmdb_id=None,  # Not linked - won't be excluded by watchlist
            first_seen=now,
            last_updated=now,
        ),
    ]

    for movie in movies:
        session.add(movie)

    # Commit movies first to get their IDs
    await session.commit()

    # Refresh to get the auto-generated IDs
    for movie in movies:
        await session.refresh(movie)

    # Create price history for all movies
    price_history = [
        # Regular Blu-rays
        PriceHistory(movie_id=movies[0].id, product_id="movie-1", price=10.99, checked_at=now),
        PriceHistory(movie_id=movies[1].id, product_id="movie-2", price=15.99, checked_at=now),
        # 4K Blu-rays
        PriceHistory(movie_id=movies[2].id, product_id="movie-3", price=25.99, checked_at=now),
        PriceHistory(movie_id=movies[3].id, product_id="movie-4", price=20.99, checked_at=now),
    ]

    for price in price_history:
        session.add(price)

    # Add TMDB movie-1001 and movie-1003 to watchlist (one regular Blu-ray, one 4K)
    watchlist = [
        Watchlist(
            tmdb_id=1001,  # movie-1's TMDB ID
            target_price=8.99,
            created_at=now,
        ),
        Watchlist(
            tmdb_id=1003,  # movie-3's TMDB ID
            target_price=20.00,
            created_at=now,
        ),
    ]

    for item in watchlist:
        session.add(item)

    await session.commit()


class TestWatchlistExclusion:
    """Test that watchlisted movies are excluded from cheapest lists."""

    async def test_get_cheapest_blurays_excludes_watchlisted(self, test_db_session):
        """Test that watchlisted Blu-ray movies are excluded from cheapest list."""
        repo = DatabaseRepository(test_db_session)

        # Get cheapest Blu-rays
        movies = await repo.get_cheapest_blurays(limit=10)

        # Should only return movie-2 (movie-1 is watchlisted via TMDB ID)
        assert len(movies) == 1
        assert movies[0].product_id == "movie-2"
        assert movies[0].title == "Test Movie 2"
        assert movies[0].current_price == 15.99

    async def test_get_cheapest_4k_blurays_excludes_watchlisted(self, test_db_session):
        """Test that watchlisted 4K Blu-ray movies are excluded from cheapest list."""
        repo = DatabaseRepository(test_db_session)

        # Get cheapest 4K Blu-rays
        movies = await repo.get_cheapest_4k_blurays(limit=10)

        # Should only return movie-4 (movie-3 is watchlisted via TMDB ID)
        assert len(movies) == 1
        assert movies[0].product_id == "movie-4"
        assert movies[0].title == "Test Movie 4"
        assert movies[0].current_price == 20.99

    async def test_cheapest_lists_with_no_watchlist_items(self, test_db_session):
        """Test that lists work normally when no items are watchlisted."""
        repo = DatabaseRepository(test_db_session)

        # Remove all watchlist items
        from sqlmodel import delete

        await test_db_session.execute(delete(Watchlist))
        await test_db_session.commit()

        # Get cheapest Blu-rays - should return both movies
        bluray_movies = await repo.get_cheapest_blurays(limit=10)
        assert len(bluray_movies) == 2

        # Should be sorted by price (cheapest first)
        assert bluray_movies[0].product_id == "movie-1"  # 10.99
        assert bluray_movies[1].product_id == "movie-2"  # 15.99

        # Get cheapest 4K Blu-rays - should return both movies
        fourk_movies = await repo.get_cheapest_4k_blurays(limit=10)
        assert len(fourk_movies) == 2

        # Should be sorted by price (cheapest first)
        assert fourk_movies[0].product_id == "movie-4"  # 20.99
        assert fourk_movies[1].product_id == "movie-3"  # 25.99

    async def test_cheapest_lists_with_all_movies_watchlisted(self, test_db_session):
        """Test that lists return empty when all TMDB-linked movies are watchlisted."""
        repo = DatabaseRepository(test_db_session)
        now = datetime.now(UTC)

        # Get all movies to link movie-2 and movie-4 to TMDB
        from sqlmodel import select

        result = await test_db_session.execute(select(Movie))
        all_movies = result.scalars().all()

        # Find movie-2 and movie-4 by product_id
        movie_2 = next(m for m in all_movies if m.product_id == "movie-2")
        movie_4 = next(m for m in all_movies if m.product_id == "movie-4")

        # Create TMDB records for movie-2 and movie-4
        tmdb_movies = [
            TMDBMovie(tmdb_id=1002, title="Test Movie 2", release_year=2020, created_at=now),
            TMDBMovie(tmdb_id=1004, title="Test Movie 4", release_year=2021, created_at=now),
        ]
        for tmdb_movie in tmdb_movies:
            test_db_session.add(tmdb_movie)
        await test_db_session.commit()

        # Link movie-2 and movie-4 to TMDB
        movie_2.tmdb_id = 1002
        movie_2.tmdb_status = "verified"
        movie_4.tmdb_id = 1004
        movie_4.tmdb_status = "verified"
        await test_db_session.commit()

        # Add remaining movies to watchlist
        additional_watchlist = [
            Watchlist(
                tmdb_id=1002,  # movie-2's TMDB ID
                target_price=12.99,
                created_at=now,
            ),
            Watchlist(
                tmdb_id=1004,  # movie-4's TMDB ID
                target_price=18.99,
                created_at=now,
            ),
        ]

        for item in additional_watchlist:
            test_db_session.add(item)
        await test_db_session.commit()

        # Both lists should be empty
        bluray_movies = await repo.get_cheapest_blurays(limit=10)
        assert len(bluray_movies) == 0

        fourk_movies = await repo.get_cheapest_4k_blurays(limit=10)
        assert len(fourk_movies) == 0
