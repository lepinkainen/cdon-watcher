"""Unit tests for configuration loading."""

import os
from unittest.mock import patch

import pytest

from src.cdon_watcher.config import load_config


class TestConfigLoading:
    """Test configuration loading from environment variables."""

    def test_load_config_defaults(self) -> None:
        """Test configuration loading with default values."""
        with patch.dict(os.environ, {}, clear=True):
            config = load_config()

            # Check default values
            assert config["check_interval_hours"] == 6
            assert config["email_enabled"] is False
            assert config["email_from"] == ""
            assert config["email_to"] == ""
            assert config["email_password"] == ""
            assert config["smtp_server"] == "smtp.gmail.com"
            assert config["smtp_port"] == 587
            assert config["discord_webhook"] is None
            assert config["api_host"] == "0.0.0.0"
            assert config["api_port"] == 8080
            assert config["api_debug"] is False
            assert config["db_path"] == "./data/cdon_movies.db"
            assert config["tmdb_api_key"] == ""
            assert config["poster_dir"] == "./data/posters"

    def test_load_config_custom_values(self) -> None:
        """Test configuration loading with custom environment values."""
        custom_env = {
            "CHECK_INTERVAL_HOURS": "12",
            "EMAIL_ENABLED": "true",
            "EMAIL_FROM": "test@example.com",
            "EMAIL_TO": "user@example.com",
            "EMAIL_PASSWORD": "secret123",
            "SMTP_SERVER": "smtp.custom.com",
            "SMTP_PORT": "465",
            "DISCORD_WEBHOOK": "https://discord.com/webhook/123",
            "API_HOST": "127.0.0.1",
            "API_PORT": "3000",
            "API_DEBUG": "true",
            "DB_PATH": "/custom/path/movies.db",
            "TMDB_API_KEY": "tmdb_key_123",
            "POSTER_DIR": "/custom/posters",
        }

        with patch.dict(os.environ, custom_env, clear=True):
            config = load_config()

            # Check custom values
            assert config["check_interval_hours"] == 12
            assert config["email_enabled"] is True
            assert config["email_from"] == "test@example.com"
            assert config["email_to"] == "user@example.com"
            assert config["email_password"] == "secret123"
            assert config["smtp_server"] == "smtp.custom.com"
            assert config["smtp_port"] == 465
            assert config["discord_webhook"] == "https://discord.com/webhook/123"
            assert config["api_host"] == "127.0.0.1"
            assert config["api_port"] == 3000
            assert config["api_debug"] is True
            assert config["db_path"] == "/custom/path/movies.db"
            assert config["tmdb_api_key"] == "tmdb_key_123"
            assert config["poster_dir"] == "/custom/posters"

    @pytest.mark.parametrize(
        "env_value,expected",
        [
            ("true", True),
            ("TRUE", True),
            ("True", True),
            ("false", False),
            ("FALSE", False),
            ("False", False),
            ("yes", False),  # Only "true" (case-insensitive) should be True
            ("1", False),
            ("", False),
        ],
    )
    def test_boolean_conversion(self, env_value: str, expected: bool) -> None:
        """Test boolean environment variable conversion."""
        with patch.dict(os.environ, {"EMAIL_ENABLED": env_value}, clear=True):
            config = load_config()
            assert config["email_enabled"] is expected

    @pytest.mark.parametrize(
        "env_value,expected",
        [
            ("42", 42),
            ("0", 0),
            ("999", 999),
            # Invalid values should raise ValueError (handled by int())
        ],
    )
    def test_integer_conversion_valid(self, env_value: str, expected: int) -> None:
        """Test valid integer environment variable conversion."""
        with patch.dict(os.environ, {"CHECK_INTERVAL_HOURS": env_value}, clear=True):
            config = load_config()
            assert config["check_interval_hours"] == expected

    def test_integer_conversion_invalid(self) -> None:
        """Test invalid integer environment variable conversion."""
        with patch.dict(os.environ, {"CHECK_INTERVAL_HOURS": "not_a_number"}, clear=True):
            with pytest.raises(ValueError):
                load_config()

    def test_mixed_environment(self) -> None:
        """Test configuration loading with mixed environment variables."""
        mixed_env = {
            "CHECK_INTERVAL_HOURS": "8",
            "EMAIL_ENABLED": "true",
            "API_DEBUG": "false",
            "DB_PATH": "/custom/db.sqlite",
            # Leave others as defaults
        }

        with patch.dict(os.environ, mixed_env, clear=True):
            config = load_config()

            # Check overridden values
            assert config["check_interval_hours"] == 8
            assert config["email_enabled"] is True
            assert config["api_debug"] is False
            assert config["db_path"] == "/custom/db.sqlite"

            # Check default values still apply
            assert config["smtp_server"] == "smtp.gmail.com"
            assert config["api_host"] == "0.0.0.0"
            assert config["poster_dir"] == "./data/posters"

    def test_none_vs_empty_string(self) -> None:
        """Test handling of None vs empty string values."""
        # DISCORD_WEBHOOK defaults to None, others to empty string
        with patch.dict(os.environ, {}, clear=True):
            config = load_config()
            assert config["discord_webhook"] is None
            assert config["email_from"] == ""
            assert config["tmdb_api_key"] == ""

        # Set DISCORD_WEBHOOK to empty string
        with patch.dict(os.environ, {"DISCORD_WEBHOOK": ""}, clear=True):
            config = load_config()
            assert config["discord_webhook"] == ""  # Not None when explicitly set
