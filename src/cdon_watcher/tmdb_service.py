"""TMDB API service for fetching movie metadata and poster images."""

import logging
import re
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

# Confidence thresholds
CONFIDENCE_AUTO_CONFIRM = 0.95  # Skip dialog for near-perfect matches
CONFIDENCE_HIGH = 0.85
CONFIDENCE_MEDIUM = 0.60


@dataclass
class TMDBCandidateData:
    """TMDB candidate for disambiguation."""

    tmdb_id: int
    imdb_id: str | None = None
    title: str = ""
    original_title: str | None = None
    release_year: int | None = None
    poster_path: str | None = None
    overview: str | None = None
    director: str | None = None
    cast: list[str] = field(default_factory=list)
    popularity: float = 0.0
    content_type: str = "movie"
    confidence_score: float = 0.0


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
        self.last_request_time = int(time.time())

    def _is_tv_series(self, title: str) -> bool:
        """Detect if a title refers to a TV series rather than a movie."""
        tv_indicators = [
            r"\bSeason\s+\d+",
            r"\bSeries\s+\d+",
            r"\bComplete\s+Series",
            r"\bTV\s+Series",
            r"\bSeason\s+\d+[-–]\d*",  # Season 1-3
            r"\bS\d+\b",  # S01, S02, etc.
            r"\bEpisode\s+\d+",
            r"\bComplete\s+Collection",  # Often indicates TV box sets
            r"\bComplete\s+Seasons",  # Dexter: Complete Seasons 1-8
            r"\bThe\s+Complete\s+Collection",  # Avatar - The Last Airbender - The Complete Collection
        ]

        for pattern in tv_indicators:
            if re.search(pattern, title, re.IGNORECASE):
                return True
        return False

    def _clean_title_for_search(self, title: str, is_tv: bool = False) -> str:
        """Clean title for better TMDB search results."""
        # Clean in order from longest to shortest patterns to avoid partial matches

        # Remove disc count and import information first
        cleaned = re.sub(r"\(\d+\s+disc\)", "", title, flags=re.IGNORECASE)
        cleaned = re.sub(r"\(Import\)", "", cleaned, flags=re.IGNORECASE)

        # Remove format specifications like "(4K Ultra + Blu-ray)", "(3D Blu-ray + Blu-ray)"
        cleaned = re.sub(
            r"\([^)]*\b(Blu-ray|DVD|4K|UHD|Ultra|3D)\b[^)]*\)", "", cleaned, flags=re.IGNORECASE
        )

        if is_tv:
            # For TV series, clean longer patterns first, then shorter ones
            # "The Complete Collection" -> "Complete Collection" -> "Collection"
            cleaned = re.sub(
                r"\s*[-–—:]*\s*The\s+Complete\s+Collection\b", "", cleaned, flags=re.IGNORECASE
            )
            cleaned = re.sub(
                r"\s*[-–—:]*\s*Complete\s+Collection\b", "", cleaned, flags=re.IGNORECASE
            )
            cleaned = re.sub(
                r"\s*[-–—:]*\s*The\s+Complete\s+Series\b", "", cleaned, flags=re.IGNORECASE
            )
            cleaned = re.sub(r"\s*[-–—:]*\s*Complete\s+Series\b", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s*[-–—:]*\s*Season\s+\d+[-–]?\d*", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s*[-–—:]*\s*Series\s+\d+", "", cleaned, flags=re.IGNORECASE)

        # Remove common Blu-ray/DVD indicators and extra info (after TV-specific cleaning)
        # Longer patterns first: "Ultimate Collector's Edition" before "Ultimate" or "Edition"
        cleaned = re.sub(
            r"\b(Ultimate\s+Collector\'s\s+Edition)\b", "", cleaned, flags=re.IGNORECASE
        )
        cleaned = re.sub(r"\b(Director\'s\s+Cut)\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(
            r"\b(Blu-ray|DVD|4K|UHD|Ultra|Ultimate|Collector\'s|Special|Edition|Extended|Cut|Collection)\b",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )

        # Remove incomplete parentheses with only punctuation/whitespace like "( + )" but preserve content like "(95)"
        cleaned = re.sub(r"\(\s*[+&\-]+\s*\)", "", cleaned)

        # Remove parenthetical year info if present
        cleaned = re.sub(r"\s*\(\d{4}\)", "", cleaned)

        # Remove any remaining empty parentheses
        cleaned = re.sub(r"\s*\(\s*\)", "", cleaned)

        # Remove extra whitespace and common punctuation
        cleaned = re.sub(r"[:\-–—]+", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        return cleaned

    def calculate_confidence(
        self, source_title: str, source_year: int | None, candidate_title: str,
        candidate_year: int | None, candidate_popularity: float
    ) -> float:
        """Calculate match confidence score (0.0-1.0)."""
        score = 0.0

        # Title similarity (fuzzy match) - max 0.5
        cleaned_source = self._clean_title_for_search(source_title).lower()
        cleaned_candidate = candidate_title.lower()
        ratio = SequenceMatcher(None, cleaned_source, cleaned_candidate).ratio()
        score += ratio * 0.5

        # Year matching - max 0.3
        if source_year and candidate_year:
            year_diff = abs(source_year - candidate_year)
            if year_diff == 0:
                score += 0.3
            elif year_diff == 1:
                score += 0.2
            elif year_diff == 2:
                score += 0.1

        # Popularity bonus (helps distinguish between similarly named films) - max 0.2
        # Normalize popularity (TMDB popularity can range widely, typical range 0-100+)
        if candidate_popularity:
            pop_score = min(candidate_popularity / 100, 1.0) * 0.2
            score += pop_score

        return min(score, 1.0)

    def get_credits(self, tmdb_id: int, content_type: str = "movie") -> tuple[str | None, list[str]]:
        """Fetch director and top cast for disambiguation."""
        self._rate_limit()

        endpoint = "movie" if content_type == "movie" else "tv"

        try:
            params = {"api_key": self.api_key_param}
            response = self.session.get(f"{self.base_url}/{endpoint}/{tmdb_id}/credits", params=params)
            response.raise_for_status()
            data = response.json()

            # Get director (for movies) or creator (for TV)
            director = None
            if content_type == "movie":
                crew = data.get("crew", [])
                directors = [c["name"] for c in crew if c.get("job") == "Director"]
                director = ", ".join(directors[:2]) if directors else None
            else:
                # For TV, creator info is in the main TV endpoint, not credits
                pass

            # Get top 3 cast members
            cast = data.get("cast", [])
            top_cast = [c["name"] for c in cast[:3]]

            return director, top_cast

        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching credits for TMDB ID {tmdb_id}: {e}")
            return None, []

    def get_external_ids(self, tmdb_id: int, content_type: str = "movie") -> dict[str, Any]:
        """Fetch external IDs including IMDB ID."""
        self._rate_limit()

        endpoint = "movie" if content_type == "movie" else "tv"

        try:
            params = {"api_key": self.api_key_param}
            response = self.session.get(f"{self.base_url}/{endpoint}/{tmdb_id}/external_ids", params=params)
            response.raise_for_status()
            external_ids: dict[str, Any] = response.json()
            return external_ids

        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching external IDs for TMDB ID {tmdb_id}: {e}")
            return {}

    def search_candidates(
        self, title: str, year: int | None = None, limit: int = 5
    ) -> list[TMDBCandidateData]:
        """Search TMDB and return multiple candidates with full metadata."""
        candidates: list[TMDBCandidateData] = []
        is_tv = self._is_tv_series(title)

        # Search for movies or TV based on title analysis
        if is_tv:
            candidates = self._search_tv_candidates(title, year, limit)
            # If no TV results, try movie search as fallback
            if not candidates:
                candidates = self._search_movie_candidates(title, year, limit)
        else:
            candidates = self._search_movie_candidates(title, year, limit)
            # If no movie results, try TV search as fallback
            if not candidates:
                candidates = self._search_tv_candidates(title, year, limit)

        # Calculate confidence scores and sort
        for candidate in candidates:
            candidate.confidence_score = self.calculate_confidence(
                title, year, candidate.title, candidate.release_year, candidate.popularity
            )

        # Sort by confidence score descending
        candidates.sort(key=lambda c: c.confidence_score, reverse=True)

        return candidates[:limit]

    def _search_movie_candidates(
        self, title: str, year: int | None = None, limit: int = 5
    ) -> list[TMDBCandidateData]:
        """Search for movies and return candidates."""
        self._rate_limit()

        cleaned_title = self._clean_title_for_search(title, is_tv=False)

        params: dict[str, str | int] = {
            "api_key": self.api_key_param,
            "query": cleaned_title,
            "include_adult": "false",
            "language": "en-US",
            "page": 1,
        }

        if year:
            params["year"] = year

        try:
            response = self.session.get(f"{self.base_url}/search/movie", params=params)
            response.raise_for_status()
            data = response.json()

            results = data.get("results", [])
            candidates: list[TMDBCandidateData] = []

            for result in results[:limit]:
                release_year = None
                if result.get("release_date"):
                    try:
                        release_year = int(result["release_date"][:4])
                    except (ValueError, IndexError):
                        pass

                candidate = TMDBCandidateData(
                    tmdb_id=result["id"],
                    title=result.get("title", ""),
                    original_title=result.get("original_title"),
                    release_year=release_year,
                    poster_path=result.get("poster_path"),
                    overview=result.get("overview"),
                    popularity=result.get("popularity", 0),
                    content_type="movie",
                )

                # Fetch additional metadata (credits, external IDs)
                director, cast = self.get_credits(candidate.tmdb_id, "movie")
                candidate.director = director
                candidate.cast = cast

                external_ids = self.get_external_ids(candidate.tmdb_id, "movie")
                candidate.imdb_id = external_ids.get("imdb_id")

                candidates.append(candidate)

            return candidates

        except requests.exceptions.RequestException as e:
            logger.error(f"Error searching TMDB movies for '{title}': {e}")
            return []

    def _search_tv_candidates(
        self, title: str, year: int | None = None, limit: int = 5
    ) -> list[TMDBCandidateData]:
        """Search for TV series and return candidates."""
        self._rate_limit()

        cleaned_title = self._clean_title_for_search(title, is_tv=True)

        params: dict[str, str | int] = {
            "api_key": self.api_key_param,
            "query": cleaned_title,
            "include_adult": "false",
            "language": "en-US",
            "page": 1,
        }

        if year:
            params["first_air_date_year"] = year

        try:
            response = self.session.get(f"{self.base_url}/search/tv", params=params)
            response.raise_for_status()
            data = response.json()

            results = data.get("results", [])
            candidates: list[TMDBCandidateData] = []

            for result in results[:limit]:
                release_year = None
                if result.get("first_air_date"):
                    try:
                        release_year = int(result["first_air_date"][:4])
                    except (ValueError, IndexError):
                        pass

                candidate = TMDBCandidateData(
                    tmdb_id=result["id"],
                    title=result.get("name", ""),
                    original_title=result.get("original_name"),
                    release_year=release_year,
                    poster_path=result.get("poster_path"),
                    overview=result.get("overview"),
                    popularity=result.get("popularity", 0),
                    content_type="tv",
                )

                # Fetch additional metadata (credits, external IDs)
                director, cast = self.get_credits(candidate.tmdb_id, "tv")
                candidate.director = director
                candidate.cast = cast

                external_ids = self.get_external_ids(candidate.tmdb_id, "tv")
                candidate.imdb_id = external_ids.get("imdb_id")

                candidates.append(candidate)

            return candidates

        except requests.exceptions.RequestException as e:
            logger.error(f"Error searching TMDB TV for '{title}': {e}")
            return []

    def get_poster_url(self, poster_path: str | None) -> str | None:
        """Get full poster URL from poster path."""
        if not poster_path:
            return None
        return f"{self.image_base_url}{poster_path}"

    # Legacy methods for backward compatibility during migration

    def search_tv(self, title: str, year: int | None = None) -> dict[str, Any] | None:
        """Search for a TV series on TMDB and return the best match."""
        self._rate_limit()

        cleaned_title = self._clean_title_for_search(title, is_tv=True)

        params: dict[str, str | int] = {
            "api_key": self.api_key_param,
            "query": cleaned_title,
            "include_adult": "false",
            "language": "en-US",
            "page": 1,
        }

        if year:
            params["first_air_date_year"] = year

        try:
            response = self.session.get(f"{self.base_url}/search/tv", params=params)
            response.raise_for_status()
            data = response.json()

            results = data.get("results", [])
            if not results:
                logger.info(f"No TMDB TV results found for: {title}")
                return None

            # Return the first result (TMDB orders by relevance)
            best_match: dict[str, Any] = results[0]
            logger.info(
                f"Found TMDB TV match for '{title}': {best_match['name']} ({best_match.get('first_air_date', 'N/A')[:4]})"
            )
            return best_match

        except requests.exceptions.RequestException as e:
            logger.error(f"Error searching TMDB TV for '{title}': {e}")
            return None

    def search_movie(self, title: str, year: int | None = None) -> dict[str, Any] | None:
        """Search for a movie on TMDB and return the best match."""
        self._rate_limit()

        cleaned_title = self._clean_title_for_search(title, is_tv=False)

        params: dict[str, str | int] = {
            "api_key": self.api_key_param,
            "query": cleaned_title,
            "include_adult": "false",
            "language": "en-US",
            "page": 1,
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
            best_match: dict[str, Any] = results[0]
            logger.info(
                f"Found TMDB match for '{title}': {best_match['title']} ({best_match.get('release_date', 'N/A')[:4]})"
            )
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
            movie_details: dict[str, Any] = response.json()
            return movie_details
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

            with open(local_poster_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            logger.info(f"Downloaded poster for TMDB ID {tmdb_id}: {poster_filename}")
            return str(local_poster_path)

        except requests.exceptions.RequestException as e:
            logger.error(f"Error downloading poster for TMDB ID {tmdb_id}: {e}")
            return None

    def get_tv_data_and_poster(
        self, title: str, year: int | None = None
    ) -> tuple[int | None, str | None]:
        """Search for TV series and download poster. Returns (tmdb_tv_id, local_poster_path)."""
        tv_data = self.search_tv(title, year)
        if not tv_data:
            return None, None

        tmdb_id = tv_data["id"]
        poster_path = tv_data.get("poster_path")

        if not poster_path:
            logger.info(f"No poster available for TMDB TV ID {tmdb_id}")
            return tmdb_id, None

        local_poster_path = self.download_poster(poster_path, tmdb_id)
        return tmdb_id, local_poster_path

    def get_movie_data_and_poster(
        self, title: str, year: int | None = None
    ) -> tuple[int | None, str | None]:
        """Search for movie/TV and download poster. Returns (tmdb_id, local_poster_path)."""
        # First try as TV series if it looks like one
        if self._is_tv_series(title):
            logger.info(f"Detected TV series, trying TV search first: {title}")
            tmdb_id, poster_path = self.get_tv_data_and_poster(title, year)
            if tmdb_id:
                return tmdb_id, poster_path

        # Try as movie (either it didn't look like TV, or TV search failed)
        movie_data = self.search_movie(title, year)
        if not movie_data:
            # If movie search failed and we haven't tried TV yet, try TV as fallback
            if not self._is_tv_series(title):
                logger.info(f"Movie search failed, trying TV search as fallback: {title}")
                return self.get_tv_data_and_poster(title, year)
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
        year_match = re.search(r"\((\d{4})\)", title)
        if year_match:
            return int(year_match.group(1))
        return None
