"""Configuration loading tests."""

import os
from pathlib import Path
from unittest.mock import patch

from cdon_watcher.config import load_config


def test_defaults():
    with patch.dict(os.environ, {}, clear=True):
        config = load_config()
    assert config["db_path"] == "./data/catalog.db"
    assert config["raw_dir"] == Path("./data/raw")
    assert config["stores"] == ["ax", "cdon"]
    assert config["max_pages"] == 10
    assert config["run_scheduler"] is False
    assert config["tmdb_api_key"] == ""


def test_overrides():
    env = {
        "DB_PATH": "/x/c.db",
        "STORES": "cdon",
        "MAX_PAGES_PER_CATEGORY": "3",
        "RUN_SCHEDULER": "true",
        "API_PORT": "9000",
        "CRAWL_DELAY_SECONDS": "0.5",
    }
    with patch.dict(os.environ, env, clear=True):
        config = load_config()
    assert config["db_path"] == "/x/c.db"
    assert config["stores"] == ["cdon"]
    assert config["max_pages"] == 3
    assert config["run_scheduler"] is True
    assert config["api_port"] == 9000
    assert config["crawl_delay"] == 0.5
