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
def index() -> Any:
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
        product_id = data.get("product_id")
        movie_id = data.get("movie_id")  # Backward compatibility
        target_price = data.get("target_price")

        if not target_price:
            return jsonify({"error": "Missing target_price"}), 400

        # Use product_id if provided, otherwise fall back to movie_id for backward compatibility
        if product_id:
            success = db.add_to_watchlist(product_id, target_price)
        elif movie_id:
            # For backward compatibility, find the product_id from movie_id
            conn = db.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT product_id FROM movies WHERE id = ?", (movie_id,))
            result = cursor.fetchone()
            conn.close()
            
            if not result or not result[0]:
                return jsonify({"error": "Movie not found or missing product_id"}), 404
            
            success = db.add_to_watchlist(result[0], target_price)
        else:
            return jsonify({"error": "Missing product_id or movie_id"}), 400

        if success:
            return jsonify({"message": "Added to watchlist"})
        else:
            return jsonify({"error": "Failed to add to watchlist"}), 500


@api_bp.route("/watchlist/<path:identifier>", methods=["DELETE"])
def api_remove_from_watchlist(identifier: Any) -> Any:
    """Remove movie from watchlist by product_id or movie_id."""
    db = DatabaseManager()
    
    # Try to determine if it's a product_id or movie_id
    try:
        # If it's an integer, treat as movie_id for backward compatibility
        movie_id = int(identifier)
        # Get product_id from movie_id
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT product_id FROM movies WHERE id = ?", (movie_id,))
        result = cursor.fetchone()
        conn.close()
        
        if not result or not result[0]:
            return jsonify({"error": "Movie not found or missing product_id"}), 404
        
        success = db.remove_from_watchlist(result[0])
    except ValueError:
        # It's a string, treat as product_id
        success = db.remove_from_watchlist(identifier)

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
    product_id = data.get("product_id")
    movie_id = data.get("movie_id")  # Backward compatibility

    if not product_id and not movie_id:
        return jsonify({"error": "Missing product_id or movie_id"}), 400

    db = DatabaseManager()
    
    if product_id:
        success = db.ignore_movie_by_product_id(product_id)
    else:
        success = db.ignore_movie(movie_id)

    if success:
        return jsonify({"message": "Movie ignored"})
    else:
        return jsonify({"error": "Failed to ignore movie"}), 500
