"""Flask routes for the web dashboard."""

from typing import Any

from flask import Blueprint, jsonify, render_template, request

from ..cdon_scraper_v2 import CDONScraper
from ..config import CONFIG
from ..database import DatabaseManager

# Create blueprints
main_bp = Blueprint("main", __name__)
api_bp = Blueprint("api", __name__)


@main_bp.route("/")
def index() -> str:
    """Main dashboard page."""
    return render_template("index.html")


@api_bp.route("/stats")
def api_stats() -> Any:
    """Get dashboard statistics."""
    db = DatabaseManager()
    stats = db.get_stats()
    return jsonify(stats)


@api_bp.route("/alerts")
def api_alerts() -> Any:
    """Get recent price alerts."""
    scraper = CDONScraper(CONFIG["db_path"])
    alerts = scraper.get_price_alerts()
    return jsonify(alerts[:10])  # Return last 10 alerts


@api_bp.route("/deals")
def api_deals() -> Any:
    """Get movies with biggest price drops."""
    db = DatabaseManager()
    deals = db.get_deals(12)
    return jsonify(deals)


@api_bp.route("/watchlist", methods=["GET", "POST", "DELETE"])
def api_watchlist() -> Any:
    """Handle watchlist operations."""
    db = DatabaseManager()

    if request.method == "GET":
        watchlist = db.get_watchlist()
        return jsonify(watchlist)

    elif request.method == "POST":
        data = request.get_json()
        movie_id = data.get("movie_id")
        target_price = data.get("target_price")

        if not movie_id or not target_price:
            return jsonify({"error": "Missing movie_id or target_price"}), 400

        success = db.add_to_watchlist(movie_id, target_price)
        if success:
            return jsonify({"message": "Added to watchlist"})
        else:
            return jsonify({"error": "Failed to add to watchlist"}), 500


@api_bp.route("/watchlist/<int:movie_id>", methods=["DELETE"])
def api_remove_from_watchlist(movie_id: Any) -> Any:
    """Remove movie from watchlist."""
    db = DatabaseManager()
    success = db.remove_from_watchlist(movie_id)

    if success:
        return jsonify({"message": "Removed from watchlist"})
    else:
        return jsonify({"error": "Failed to remove from watchlist"}), 500


@api_bp.route("/search")
def api_search() -> Any:
    """Search for movies."""
    query = request.args.get("q", "")
    if not query:
        return jsonify([])

    db = DatabaseManager()
    movies = db.search_movies(query, 20)
    return jsonify(movies)


@api_bp.route("/cheapest-blurays")
def api_cheapest_blurays() -> Any:
    """Get cheapest Blu-ray movies."""
    db = DatabaseManager()
    movies = db.get_cheapest_blurays(20)
    return jsonify(movies)


@api_bp.route("/cheapest-4k-blurays")
def api_cheapest_4k_blurays() -> Any:
    """Get cheapest 4K Blu-ray movies."""
    db = DatabaseManager()
    movies = db.get_cheapest_4k_blurays(20)
    return jsonify(movies)


@api_bp.route("/ignore-movie", methods=["POST"])
def api_ignore_movie() -> Any:
    """Add movie to ignored list."""
    data = request.get_json()
    movie_id = data.get("movie_id")

    if not movie_id:
        return jsonify({"error": "Missing movie_id"}), 400

    db = DatabaseManager()
    success = db.ignore_movie(movie_id)

    if success:
        return jsonify({"message": "Movie ignored"})
    else:
        return jsonify({"error": "Failed to ignore movie"}), 500
