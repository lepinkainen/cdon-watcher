"""Flask web application setup."""

from flask import Flask
from flask_cors import CORS


def create_app() -> Flask:
    """Create and configure Flask application."""
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    CORS(app)

    # Register blueprints
    from .routes import api_bp, main_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp, url_prefix="/api")

    return app
