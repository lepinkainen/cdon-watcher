"""
Page cache for storing fetched HTML pages with TTL support.

Uses a separate SQLite database that can be easily cleared by deleting the file.
"""

import hashlib
import logging
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from .config import CONFIG

logger = logging.getLogger(__name__)


class PageCache:
    """SQLite-based page cache with TTL support."""

    def __init__(
        self,
        db_path: str | None = None,
        ttl_hours: int | None = None,
    ) -> None:
        """Initialize the page cache.

        Args:
            db_path: Path to the cache database file. Defaults to config value.
            ttl_hours: Cache TTL in hours. Defaults to config value (12 hours).
        """
        self.db_path = db_path or CONFIG["cache_db_path"]
        self.ttl_hours = ttl_hours if ttl_hours is not None else CONFIG["cache_ttl_hours"]
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _init_db(self) -> None:
        """Initialize the cache database and create tables if needed."""
        # Ensure directory exists
        db_dir = Path(self.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS page_cache (
                url_hash TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                content BLOB NOT NULL,
                fetched_at TEXT NOT NULL
            )
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_fetched_at ON page_cache(fetched_at)
        """)
        self._conn.commit()
        logger.debug(f"Page cache initialized at {self.db_path}")

    def _url_hash(self, url: str) -> str:
        """Generate a hash for a URL to use as the cache key."""
        return hashlib.sha256(url.encode()).hexdigest()

    def get(self, url: str) -> bytes | None:
        """Get cached page content if it exists and is not expired.

        Args:
            url: The URL to look up in the cache.

        Returns:
            The cached page content as bytes, or None if not cached or expired.
        """
        if self._conn is None:
            return None

        url_hash = self._url_hash(url)
        cursor = self._conn.execute(
            "SELECT content, fetched_at FROM page_cache WHERE url_hash = ?",
            (url_hash,),
        )
        row = cursor.fetchone()

        if row is None:
            logger.debug(f"Cache miss: {url}")
            return None

        content, fetched_at_str = row
        fetched_at = datetime.fromisoformat(fetched_at_str)
        expiry_time = fetched_at + timedelta(hours=self.ttl_hours)

        if datetime.now() > expiry_time:
            logger.debug(f"Cache expired: {url} (fetched at {fetched_at_str})")
            # Clean up expired entry
            self._conn.execute("DELETE FROM page_cache WHERE url_hash = ?", (url_hash,))
            self._conn.commit()
            return None

        logger.debug(f"Cache hit: {url}")
        return bytes(content)

    def set(self, url: str, content: bytes) -> None:
        """Store page content in the cache.

        Args:
            url: The URL to cache.
            content: The page content as bytes.
        """
        if self._conn is None:
            return

        url_hash = self._url_hash(url)
        fetched_at = datetime.now().isoformat()

        self._conn.execute(
            """
            INSERT OR REPLACE INTO page_cache (url_hash, url, content, fetched_at)
            VALUES (?, ?, ?, ?)
            """,
            (url_hash, url, content, fetched_at),
        )
        self._conn.commit()
        logger.debug(f"Cached: {url}")

    def clear_expired(self) -> int:
        """Remove all expired entries from the cache.

        Returns:
            Number of entries removed.
        """
        if self._conn is None:
            return 0

        expiry_threshold = (datetime.now() - timedelta(hours=self.ttl_hours)).isoformat()
        cursor = self._conn.execute(
            "DELETE FROM page_cache WHERE fetched_at < ?",
            (expiry_threshold,),
        )
        self._conn.commit()
        removed = cursor.rowcount
        if removed > 0:
            logger.info(f"Cleared {removed} expired cache entries")
        return removed

    def get_stats(self) -> dict[str, int | str]:
        """Get cache statistics.

        Returns:
            Dictionary with cache stats (total entries, db size, etc.)
        """
        if self._conn is None:
            return {"total_entries": 0, "db_size_bytes": 0, "db_path": self.db_path}

        cursor = self._conn.execute("SELECT COUNT(*) FROM page_cache")
        total_entries = cursor.fetchone()[0]

        db_size = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0

        return {
            "total_entries": total_entries,
            "db_size_bytes": db_size,
            "db_path": self.db_path,
            "ttl_hours": self.ttl_hours,
        }

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None


# Global cache instance (lazy initialization)
_cache_instance: PageCache | None = None


def get_page_cache() -> PageCache:
    """Get the global page cache instance."""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = PageCache()
    return _cache_instance
