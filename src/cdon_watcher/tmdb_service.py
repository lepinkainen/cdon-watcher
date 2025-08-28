"""TMDB API service for fetching movie metadata and poster images."""

import logging
import re
import time
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)


class TMDBService:
    """Service for interacting with The Movie Database API."""

    def __init__(self, api_key: str, poster_dir: str = "./data/posters"):
        """Initialize TMDB service with API key and poster directory."""
        self.api_key = api_key
        self.poster_dir = Path(poster_dir)
        self.base_url = "https://api.themoviedb.org/3"
        self.image_base_url = "https://image.tmdb.org/t/p/w500"  # 500px wide posters
        self.session = requests.Session()
        # For v3 API, use api_key parameter instead of Bearer token
        self.api_key_param = api_key

        # Create poster directory if it doesn't exist
        self.poster_dir.mkdir(parents=True, exist_ok=True)

        # Rate limiting: TMDB allows ~50 requests per second
        self.last_request_time = 0
        self.min_request_interval = 0.02  # 20ms between requests

    def _rate_limit(self) -> None:
        """Ensure we don't exceed TMDB rate limits."""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        if time_since_last < self.min_request_interval:
            time.sleep(self.min_request_interval - time_since_last)
        self.last_request_time = time.time()

    def _clean_title_for_search(self, title: str) -> str:
        """Clean movie title for better TMDB search results."""
        # Remove common Blu-ray/DVD indicators and extra info
        cleaned = re.sub(r'\b(Blu-ray|DVD|4K|UHD|Ultimate|Collector\'s|Special|Edition|Extended|Director\'s|Cut)\b', '', title, flags=re.IGNORECASE)

        # Remove parenthetical year info if present
        cleaned = re.sub(r'\s*\(\d{4}\)', '', cleaned)

        # Remove extra whitespace and common punctuation
        cleaned = re.sub(r'[:\-–—]+', ' ', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()

        return cleaned

    def search_movie(self, title: str, year: int | None = None) -> dict[str, Any] | None:
        """Search for a movie on TMDB and return the best match."""
        self._rate_limit()

        cleaned_title = self._clean_title_for_search(title)

        params = {
            "api_key": self.api_key_param,
            "query": cleaned_title,
            "include_adult": "false",
            "language": "en-US",
            "page": 1
        }

        if year:
            params["year"] = year

        try:
            response = self.session.get(f"{self.base_url}/search/movie", params=params)
            response.raise_for_status()
            data = response.json()

            results = data.get("results", [])
            if not results:
                logger.info(f"No TMDB results found for: {title}")
                return None

            # Return the first result (TMDB orders by relevance)
            best_match = results[0]
            logger.info(f"Found TMDB match for '{title}': {best_match['title']} ({best_match.get('release_date', 'N/A')[:4]})")
            return best_match

        except requests.exceptions.RequestException as e:
            logger.error(f"Error searching TMDB for '{title}': {e}")
            return None

    def get_movie_details(self, tmdb_id: int) -> dict[str, Any] | None:
        """Get detailed movie information from TMDB."""
        self._rate_limit()

        try:
            params = {"api_key": self.api_key_param}
            response = self.session.get(f"{self.base_url}/movie/{tmdb_id}", params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching TMDB movie details for ID {tmdb_id}: {e}")
            return None

    def download_poster(self, poster_path: str, tmdb_id: int) -> str | None:
        """Download movie poster and return local file path."""
        if not poster_path:
            return None

        poster_filename = f"{tmdb_id}.jpg"
        local_poster_path = self.poster_dir / poster_filename

        # Skip if already downloaded
        if local_poster_path.exists():
            logger.info(f"Poster already exists for TMDB ID {tmdb_id}")
            return str(local_poster_path)

        poster_url = f"{self.image_base_url}{poster_path}"

        try:
            self._rate_limit()
            response = self.session.get(poster_url, stream=True)
            response.raise_for_status()

            with open(local_poster_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            logger.info(f"Downloaded poster for TMDB ID {tmdb_id}: {poster_filename}")
            return str(local_poster_path)

        except requests.exceptions.RequestException as e:
            logger.error(f"Error downloading poster for TMDB ID {tmdb_id}: {e}")
            return None

    def get_movie_data_and_poster(self, title: str, year: int | None = None) -> tuple[int | None, str | None]:
        """Search for movie and download poster. Returns (tmdb_id, local_poster_path)."""
        movie_data = self.search_movie(title, year)
        if not movie_data:
            return None, None

        tmdb_id = movie_data["id"]
        poster_path = movie_data.get("poster_path")

        if not poster_path:
            logger.info(f"No poster available for TMDB ID {tmdb_id}")
            return tmdb_id, None

        local_poster_path = self.download_poster(poster_path, tmdb_id)
        return tmdb_id, local_poster_path

    def extract_year_from_title(self, title: str) -> int | None:
        """Extract release year from movie title if present."""
        year_match = re.search(r'\((\d{4})\)', title)
        if year_match:
            return int(year_match.group(1))
        return None
