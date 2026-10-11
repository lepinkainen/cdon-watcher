"""Application wiring tests."""

from fastapi.testclient import TestClient

from cdon_watcher.config import CONFIG
from cdon_watcher.web.app import create_app


def test_routes_and_static(tmp_path, monkeypatch):
    monkeypatch.setitem(CONFIG, "db_path", str(tmp_path / "c.db"))
    app = create_app()
    paths = {route.path for route in app.routes}
    assert {"/", "/watchlist", "/queue", "/ignored", "/status", "/static"} <= paths
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/static/css/style.css").status_code == 200
        assert client.get("/static/js/app.js").status_code == 200
        assert client.get("/nope").status_code == 404


def test_scheduler_stays_off_by_default(tmp_path, monkeypatch):
    monkeypatch.setitem(CONFIG, "db_path", str(tmp_path / "c.db"))
    monkeypatch.setitem(CONFIG, "run_scheduler", False)
    with TestClient(create_app()) as client:
        assert client.get("/status").status_code == 200
