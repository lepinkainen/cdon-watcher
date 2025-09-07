"""Configuration management for CDON Watcher."""

import os
from typing import Any


def load_config() -> dict[str, Any]:
    """Load configuration from environment variables."""
    return {
        "check_interval_hours": int(os.environ.get("CHECK_INTERVAL_HOURS", 6)),
        "discord_webhook": os.environ.get("DISCORD_WEBHOOK", None),
        "api_host": os.environ.get("API_HOST", "0.0.0.0"),
        "api_port": int(os.environ.get("API_PORT", 8080)),
        "api_debug": os.environ.get("API_DEBUG", "false").lower() == "true",
        "db_path": os.environ.get("DB_PATH", "./data/cdon_movies.db"),
        "tmdb_api_key": os.environ.get("TMDB_API_KEY", ""),
        "poster_dir": os.environ.get("POSTER_DIR", "./data/posters"),
        # Scan mode configurations
        "scan_mode": os.environ.get("SCAN_MODE", "fast"),  # fast, moderate, slow
        "fast_scan_delay": int(os.environ.get("FAST_SCAN_DELAY", 2)),  # seconds
        "moderate_scan_delay": int(
            os.environ.get("MODERATE_SCAN_DELAY", 180)
        ),  # seconds (3 minutes)
        "slow_scan_delay": int(os.environ.get("SLOW_SCAN_DELAY", 1800)),  # seconds (30 minutes)
        "production_mode": os.environ.get("PRODUCTION_MODE", "false").lower() == "true",
        "min_deal_diff": float(os.environ.get("MIN_DEAL_DIFF", "5.0")),  # minimum deal difference in euros
    }


# Global config instance
CONFIG = load_config()
