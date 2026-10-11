"""Configuration from environment variables (and .env when present)."""

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def load_config() -> dict[str, Any]:
    stores = [s.strip() for s in os.environ.get("STORES", "ax,cdon").split(",") if s.strip()]
    return {
        "db_path": os.environ.get("DB_PATH", "./data/catalog.db"),
        "raw_dir": Path(os.environ.get("RAW_DIR", "./data/raw")),
        "tmdb_api_key": os.environ.get("TMDB_API_KEY", ""),
        "api_host": os.environ.get("API_HOST", "0.0.0.0"),
        "api_port": int(os.environ.get("API_PORT", 8080)),
        "api_debug": _bool("API_DEBUG", False),
        "stores": stores,
        "max_pages": int(os.environ.get("MAX_PAGES_PER_CATEGORY", 10)),
        "crawl_delay": float(os.environ.get("CRAWL_DELAY_SECONDS", 2.0)),
        "crawl_attempts": int(os.environ.get("CRAWL_ATTEMPTS", 3)),
        "run_scheduler": _bool("RUN_SCHEDULER", False),
        "scheduler_interval_hours": float(os.environ.get("SCHEDULER_INTERVAL_HOURS", 24)),
        "scheduler_initial_delay": float(os.environ.get("SCHEDULER_INITIAL_DELAY_SECONDS", 300)),
    }


CONFIG = load_config()
