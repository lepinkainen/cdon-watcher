"""Flask web application setup."""

import os

from flask import Flask
from flask_cors import CORS


def create_app() -> Flask:
    """Create and configure Flask application."""
    # Get absolute paths for templates and static folders
    current_dir = os.path.dirname(os.path.abspath(__file__))
    template_folder = os.path.join(os.path.dirname(current_dir), "templates")
    static_folder = os.path.join(os.path.dirname(current_dir), "static")

    app = Flask(__name__, template_folder=template_folder, static_folder=static_folder)

    # Initialize CORS and store reference in app.extensions
    cors = CORS(app)
    app.extensions["cors"] = cors

    # Register blueprints
    from .routes import api_bp, main_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp, url_prefix="/api")

    return app
