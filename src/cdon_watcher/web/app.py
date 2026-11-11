"""FastAPI application: catalog UI plus the optional in-process scheduler."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..catalog.db import open_catalog
from ..config import CONFIG
from ..scheduler import start_scheduler
from .catalog_routes import router
from .filters import register_filters


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.catalog_engine = open_catalog(CONFIG["db_path"])
    scheduler_task = start_scheduler()
    try:
        yield
    finally:
        if scheduler_task is not None:
            scheduler_task.cancel()
            try:
                await scheduler_task
            except BaseException:
                pass


def create_app() -> FastAPI:
    app = FastAPI(title="Movie offers", version="1.0.0", lifespan=lifespan)
    package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    static_folder = os.path.join(package_dir, "static")
    templates_folder = os.path.join(package_dir, "templates")
    if os.path.exists(static_folder):
        app.mount("/static", StaticFiles(directory=static_folder), name="static")
    templates = Jinja2Templates(directory=templates_folder)
    register_filters(templates)
    app.state.templates = templates
    app.include_router(router)
    return app
