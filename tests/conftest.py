"""Shared pytest configuration. Catalog tests build their own temporary databases."""

import pytest

from shelfwatch.config import CONFIG


@pytest.fixture(autouse=True)
def _no_jev(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests never call Jev, even when JEV_API_KEY is set in the shell."""
    monkeypatch.setitem(CONFIG, "jev_api_key", "")
