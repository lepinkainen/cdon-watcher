"""Unit tests for search filtering functionality."""

import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.cdon_watcher.database.repository import DatabaseRepository
from src.cdon_watcher.models import Movie, PriceHistory


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
    from src.cdon_watcher.config import CONFIG

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
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with test_session_local() as session:
        # Add test movies with different formats and prices
        movies_data = [
            {
                "product_id": "test-bluray-1",
                "title": "Test Bluray Movie 1",
                "format": "Blu-ray",
                "price": 15.99,
            },
            {
                "product_id": "test-bluray-2",
                "title": "Another Bluray Film",
                "format": "Blu-ray",
                "price": 25.50,
            },
            {
                "product_id": "test-4k-1",
                "title": "Test 4K Movie",
                "format": "4K Ultra HD Blu-ray",
                "price": 35.99,
            },
            {
                "product_id": "test-4k-2",
                "title": "Another 4K Film",
                "format": "4K Blu-ray",
                "price": 19.99,
            },
            {
                "product_id": "test-dvd-1",
                "title": "Test DVD Movie",
                "format": "DVD",
                "price": 9.99,
            },
        ]

        for movie_data in movies_data:
            movie = Movie(
                product_id=movie_data["product_id"],
                title=movie_data["title"],
                format=movie_data["format"],
                url=f"https://example.com/{movie_data['product_id']}",
                first_seen=datetime.now(UTC),
                last_updated=datetime.now(UTC),
            )
            session.add(movie)

        await session.commit()

        # Add price history for each movie
        for movie_data in movies_data:
            # Get the movie we just created
            from sqlmodel import select

            result = await session.execute(
                select(Movie).where(Movie.product_id == movie_data["product_id"])
            )
            movie = result.scalar_one()

            price_history = PriceHistory(
                movie_id=movie.id,
                product_id=movie_data["product_id"],
                price=movie_data["price"],
                checked_at=datetime.now(UTC),
            )
            session.add(price_history)

        await session.commit()
        yield session

    # Clean up
    await engine.dispose()


@pytest.fixture
async def test_repository(test_db_session):
    """Create a test repository instance."""
    return DatabaseRepository(test_db_session, enable_query_logging=True)


class TestSearchFiltering:
    """Test search filtering functionality."""

    async def test_basic_search_no_filters(self, test_repository):
        """Test basic search without any filters."""
        results = await test_repository.search_movies("Test")

        assert len(results) == 3  # Should find "Test" in 3 movies
        titles = [movie.title for movie in results]
        assert "Test Bluray Movie 1" in titles
        assert "Test 4K Movie" in titles
        assert "Test DVD Movie" in titles

        # Results should be ordered by price (lowest to highest)
        assert results[0].current_price == 9.99  # DVD
        assert results[1].current_price == 15.99  # Blu-ray 1
        assert results[2].current_price == 35.99  # 4K Movie

    async def test_search_with_max_price_filter(self, test_repository):
        """Test search with maximum price filter."""
        results = await test_repository.search_movies("Test", max_price=20.0)

        assert len(results) == 2  # Should find movies under €20 that contain "Test"
        prices = [movie.current_price for movie in results]
        assert all(price <= 20.0 for price in prices if price is not None)

        # Results should be ordered by price ascending
        assert results[0].current_price == 9.99  # DVD
        assert results[1].current_price == 15.99  # Blu-ray 1

    async def test_search_bluray_category_only(self, test_repository):
        """Test search with Blu-ray category filter."""
        results = await test_repository.search_movies("", category="bluray")

        assert len(results) == 2  # Should find 2 Blu-ray movies
        for movie in results:
            assert "Blu-ray" in movie.format
            assert "4K" not in movie.format

    async def test_search_4k_category_only(self, test_repository):
        """Test search with 4K category filter."""
        results = await test_repository.search_movies("", category="4k")

        assert len(results) == 2  # Should find 2 4K movies
        for movie in results:
            assert "4K" in movie.format

    async def test_search_with_price_and_category_filters(self, test_repository):
        """Test search with both price and category filters."""
        results = await test_repository.search_movies("", max_price=30.0, category="4k")

        assert len(results) == 1  # Should find only one 4K movie under €30
        assert results[0].title == "Another 4K Film"
        assert results[0].current_price == 19.99

    async def test_search_with_query_and_filters(self, test_repository):
        """Test search with query text and filters combined."""
        results = await test_repository.search_movies("Another", max_price=30.0)

        assert len(results) == 2  # Should find "Another Bluray Film" and "Another 4K Film"
        titles = [movie.title for movie in results]
        assert "Another Bluray Film" in titles
        assert "Another 4K Film" in titles

        # Results should be ordered by price ascending
        assert results[0].current_price == 19.99  # 4K film (cheaper)
        assert results[1].current_price == 25.50  # Blu-ray film (more expensive)

    async def test_search_empty_results(self, test_repository):
        """Test search that returns no results."""
        results = await test_repository.search_movies("NonexistentMovie")

        assert len(results) == 0

    async def test_search_price_filter_excludes_expensive_items(self, test_repository):
        """Test that price filter properly excludes expensive items."""
        results = await test_repository.search_movies("", max_price=10.0)

        assert len(results) == 1  # Only DVD movie should match
        assert results[0].title == "Test DVD Movie"
        assert results[0].current_price == 9.99
