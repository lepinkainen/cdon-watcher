"""FastAPI web application setup."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..database.connection import init_db
from .routes import router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan manager."""
    # Initialize database on startup
    await init_db()
    yield


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(
        title="CDON Watcher API",
        description="API for CDON Blu-ray price tracking",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Get absolute paths for static and template folders
    current_dir = os.path.dirname(os.path.abspath(__file__))
    static_folder = os.path.join(os.path.dirname(current_dir), "static")
    templates_folder = os.path.join(os.path.dirname(current_dir), "templates")

    # Mount static files
    if os.path.exists(static_folder):
        app.mount("/static", StaticFiles(directory=static_folder), name="static")

    # Set up Jinja2 templates
    templates = Jinja2Templates(directory=templates_folder)

    # Pass templates to routes (we'll add this to the router)
    app.state.templates = templates

    # Include routers
    app.include_router(router)

    return app
