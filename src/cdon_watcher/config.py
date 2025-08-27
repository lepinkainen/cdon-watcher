"""Configuration management for CDON Watcher."""

import os
from typing import Any


def load_config() -> dict[str, Any]:
    """Load configuration from environment variables."""
    return {
        "check_interval_hours": int(os.environ.get("CHECK_INTERVAL_HOURS", 6)),
        "email_enabled": os.environ.get("EMAIL_ENABLED", "false").lower() == "true",
        "email_from": os.environ.get("EMAIL_FROM", ""),
        "email_to": os.environ.get("EMAIL_TO", ""),
        "email_password": os.environ.get("EMAIL_PASSWORD", ""),
        "smtp_server": os.environ.get("SMTP_SERVER", "smtp.gmail.com"),
        "smtp_port": int(os.environ.get("SMTP_PORT", 587)),
        "discord_webhook": os.environ.get("DISCORD_WEBHOOK", None),
        "flask_host": os.environ.get("FLASK_HOST", "0.0.0.0"),
        "flask_port": int(os.environ.get("FLASK_PORT", 8080)),
        "flask_debug": os.environ.get("FLASK_DEBUG", "false").lower() == "true",
        "db_path": os.environ.get("DB_PATH", "/app/data/cdon_movies.db"),
    }


# Global config instance
CONFIG = load_config()
