"""Database operations for CDON Watcher."""

import sqlite3
from typing import Any

from .config import CONFIG


class DatabaseManager:
    """Handles all database operations."""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or CONFIG["db_path"]

    def get_connection(self) -> sqlite3.Connection:
        """Get a database connection."""
        return sqlite3.connect(self.db_path)

    def get_stats(self) -> dict[str, Any]:
        """Get dashboard statistics."""
        conn = self.get_connection()
        cursor = conn.cursor()

        # Get statistics
        cursor.execute("SELECT COUNT(*) FROM movies")
        total_movies = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*) FROM price_alerts
            WHERE DATE(created_at) = DATE('now')
        """)
        price_drops_today = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM watchlist")
        watchlist_count = cursor.fetchone()[0]

        cursor.execute("SELECT MAX(last_updated) FROM movies")
        last_update = cursor.fetchone()[0]

        conn.close()

        return {
            "total_movies": total_movies,
            "price_drops_today": price_drops_today,
            "watchlist_count": watchlist_count,
            "last_update": last_update,
        }

    def get_deals(self, limit: int = 12) -> list[dict[str, Any]]:
        """Get movies with biggest price drops."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT m.*,
                   ph1.price as current_price,
                   ph2.price as previous_price,
                   (ph2.price - ph1.price) as price_change,
                   (SELECT MIN(price) FROM price_history WHERE movie_id = m.id) as lowest_price,
                   (SELECT MAX(price) FROM price_history WHERE movie_id = m.id) as highest_price
            FROM movies m
            JOIN price_history ph1 ON m.id = ph1.movie_id
            LEFT JOIN price_history ph2 ON m.id = ph2.movie_id AND ph2.id < ph1.id
            WHERE ph1.id = (SELECT MAX(id) FROM price_history WHERE movie_id = m.id)
            AND ph2.id = (SELECT MAX(id) FROM price_history WHERE movie_id = m.id AND id < ph1.id)
            AND ph1.price < ph2.price
            ORDER BY (ph2.price - ph1.price) ASC
            LIMIT ?
        """,
            (limit,),
        )

        deals = []
        for row in cursor.fetchall():
            deals.append(
                {
                    "id": row[0],
                    "product_id": row[1],
                    "title": row[2],
                    "format": row[3],
                    "url": row[4],
                    "image_url": row[5],
                    "tmdb_id": row[6],
                    "current_price": row[9],
                    "previous_price": row[10],
                    "price_change": row[11],
                    "lowest_price": row[12],
                    "highest_price": row[13],
                }
            )

        conn.close()
        return deals

    def get_watchlist(self) -> list[dict[str, Any]]:
        """Get all watchlist items."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT m.*, w.target_price,
                   (SELECT price FROM price_history WHERE movie_id = m.id ORDER BY checked_at DESC LIMIT 1) as current_price,
                   (SELECT MIN(price) FROM price_history WHERE movie_id = m.id) as lowest_price,
                   (SELECT MAX(price) FROM price_history WHERE movie_id = m.id) as highest_price
            FROM watchlist w
            JOIN movies m ON w.movie_id = m.id
        """)

        watchlist = []
        for row in cursor.fetchall():
            watchlist.append(
                {
                    "id": row[0],
                    "product_id": row[1],
                    "title": row[2],
                    "format": row[3],
                    "url": row[4],
                    "image_url": row[5],
                    "tmdb_id": row[6],
                    "content_type": row[7],
                    "first_seen": row[8],
                    "last_updated": row[9],
                    "target_price": row[10],
                    "current_price": row[11],
                    "lowest_price": row[12],
                    "highest_price": row[13],
                }
            )

        conn.close()
        return watchlist

    def add_to_watchlist(self, product_id: str, target_price: float) -> bool:
        """Add a movie to watchlist by product_id."""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()

            # Get movie_id from product_id for backward compatibility
            cursor.execute("SELECT id FROM movies WHERE product_id = ?", (product_id,))
            result = cursor.fetchone()
            if not result:
                conn.close()
                return False

            movie_id = result[0]

            cursor.execute(
                """
                INSERT OR REPLACE INTO watchlist (movie_id, product_id, target_price, created_at)
                VALUES (?, ?, ?, datetime('now'))
            """,
                (movie_id, product_id, target_price),
            )

            conn.commit()
            conn.close()
            return True
        except Exception:
            return False

    def remove_from_watchlist(self, product_id: str) -> bool:
        """Remove a movie from watchlist by product_id."""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()

            cursor.execute("DELETE FROM watchlist WHERE product_id = ?", (product_id,))

            conn.commit()
            conn.close()
            return True
        except Exception:
            return False

    def search_movies(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search for movies by title."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT m.*,
                   (SELECT price FROM price_history WHERE movie_id = m.id ORDER BY checked_at DESC LIMIT 1) as current_price,
                   (SELECT MIN(price) FROM price_history WHERE movie_id = m.id) as lowest_price,
                   (SELECT MAX(price) FROM price_history WHERE movie_id = m.id) as highest_price
            FROM movies m
            WHERE LOWER(m.title) LIKE LOWER(?)
            ORDER BY m.title
            LIMIT ?
        """,
            (f"%{query}%", limit),
        )

        movies = []
        for row in cursor.fetchall():
            movies.append(
                {
                    "id": row[0],
                    "product_id": row[1],
                    "title": row[2],
                    "format": row[3],
                    "url": row[4],
                    "image_url": row[5],
                    "tmdb_id": row[6],
                    "current_price": row[9],
                    "lowest_price": row[10],
                    "highest_price": row[11],
                }
            )

        conn.close()
        return movies

    def get_cheapest_blurays(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get cheapest Blu-ray movies."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT m.*, ph.price as current_price,
                   (SELECT MIN(price) FROM price_history WHERE movie_id = m.id) as lowest_price,
                   (SELECT MAX(price) FROM price_history WHERE movie_id = m.id) as highest_price
            FROM movies m
            JOIN price_history ph ON m.id = ph.movie_id
            WHERE ph.id = (SELECT MAX(id) FROM price_history WHERE movie_id = m.id)
            AND m.format LIKE '%Blu-ray%' AND m.format NOT LIKE '%4K%'
            AND m.id NOT IN (SELECT movie_id FROM ignored_movies)
            ORDER BY ph.price ASC
            LIMIT ?
        """,
            (limit,),
        )

        movies = []
        for row in cursor.fetchall():
            movies.append(
                {
                    "id": row[0],
                    "product_id": row[1],
                    "title": row[2],
                    "format": row[3],
                    "url": row[4],
                    "image_url": row[5],
                    "tmdb_id": row[6],
                    "current_price": row[9],
                    "lowest_price": row[10],
                    "highest_price": row[11],
                }
            )

        conn.close()
        return movies

    def get_cheapest_4k_blurays(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get cheapest 4K Blu-ray movies."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT m.*, ph.price as current_price,
                   (SELECT MIN(price) FROM price_history WHERE movie_id = m.id) as lowest_price,
                   (SELECT MAX(price) FROM price_history WHERE movie_id = m.id) as highest_price
            FROM movies m
            JOIN price_history ph ON m.id = ph.movie_id
            WHERE ph.id = (SELECT MAX(id) FROM price_history WHERE movie_id = m.id)
            AND m.format LIKE '%4K%'
            AND m.id NOT IN (SELECT movie_id FROM ignored_movies)
            ORDER BY ph.price ASC
            LIMIT ?
        """,
            (limit,),
        )

        movies = []
        for row in cursor.fetchall():
            movies.append(
                {
                    "id": row[0],
                    "product_id": row[1],
                    "title": row[2],
                    "format": row[3],
                    "url": row[4],
                    "image_url": row[5],
                    "tmdb_id": row[6],
                    "current_price": row[9],
                    "lowest_price": row[10],
                    "highest_price": row[11],
                }
            )

        conn.close()
        return movies

    def ignore_movie(self, movie_id: int) -> bool:
        """Add a movie to the ignored list by movie_id (legacy method)."""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()

            # Get product_id for the movie
            cursor.execute("SELECT product_id FROM movies WHERE id = ?", (movie_id,))
            result = cursor.fetchone()
            product_id = result[0] if result else None

            cursor.execute(
                """
                INSERT OR IGNORE INTO ignored_movies (movie_id, product_id, ignored_at)
                VALUES (?, ?, datetime('now'))
            """,
                (movie_id, product_id),
            )

            conn.commit()
            conn.close()
            return True
        except Exception:
            return False

    def ignore_movie_by_product_id(self, product_id: str) -> bool:
        """Add a movie to the ignored list by product_id."""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()

            # Get movie_id from product_id for backward compatibility
            cursor.execute("SELECT id FROM movies WHERE product_id = ?", (product_id,))
            result = cursor.fetchone()
            if not result:
                conn.close()
                return False

            movie_id = result[0]

            cursor.execute(
                """
                INSERT OR IGNORE INTO ignored_movies (movie_id, product_id, ignored_at)
                VALUES (?, ?, datetime('now'))
            """,
                (movie_id, product_id),
            )

            conn.commit()
            conn.close()
            return True
        except Exception:
            return False
