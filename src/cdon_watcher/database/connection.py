"""Database connection and initialization for SQLModel."""

from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from ..config import CONFIG

# Ensure database directory exists
db_path = Path(CONFIG["db_path"])
db_path.parent.mkdir(parents=True, exist_ok=True)

# Create async engine
engine = create_async_engine(
    f"sqlite+aiosqlite:///{CONFIG['db_path']}",
    echo=False,  # Set to True for SQL debugging
    future=True,
)

# Create session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    """Initialize database tables."""
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    # Run migrations for existing databases
    await _run_migrations()


async def _run_migrations() -> None:
    """Run database migrations for schema changes."""
    from sqlalchemy import text

    async with engine.begin() as conn:
        # Migration: Add 'available' column if it doesn't exist
        # SQLite will error if column already exists, which we can safely ignore
        try:
            await conn.execute(
                text("ALTER TABLE movies ADD COLUMN available BOOLEAN DEFAULT 1")
            )
        except Exception:
            pass  # Column already exists

        # Migration: Add 'is_box_set' column if it doesn't exist
        try:
            await conn.execute(
                text("ALTER TABLE movies ADD COLUMN is_box_set BOOLEAN DEFAULT 0")
            )
        except Exception:
            pass  # Column already exists


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Get database session for dependency injection."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
