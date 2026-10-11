"""Routes for the multi-store catalog UI. Sync handlers over a sync engine."""

from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import Engine
from starlette.responses import Response

from ..catalog import preferences, queries
from ..catalog.db import open_catalog
from ..catalog.matching import set_manual_match
from ..catalog.tmdb import HttpTmdbClient, TmdbClient, TmdbError
from ..config import CONFIG

router = APIRouter()

ACTIONS = ("watch", "unwatch", "ignore", "unignore")
FORMATS = ("bd", "4k")
CONDITIONS = ("new", "used")


def _engine(request: Request) -> Engine:
    engine: Engine | None = getattr(request.app.state, "catalog_engine", None)
    if engine is None:
        engine = open_catalog(CONFIG["db_path"])
        request.app.state.catalog_engine = engine
    return engine


def _tmdb_client(request: Request) -> TmdbClient | None:
    client = getattr(request.app.state, "tmdb_client", None)
    if client is not None:
        return client  # type: ignore[no-any-return]
    key = CONFIG.get("tmdb_api_key")
    if not key:
        return None
    client = HttpTmdbClient(key)
    request.app.state.tmdb_client = client
    return client


def _euros_to_cents(value: str | None, default: int) -> int:
    if value is None or value.strip() == "":
        return default
    try:
        cents = int((Decimal(value.replace(",", ".")) * 100).to_integral_value())
    except InvalidOperation as error:
        raise HTTPException(400, f"Invalid price {value!r}") from error
    if cents < 0:
        raise HTTPException(400, "Price limits must be positive")
    return cents


def _display_euros(cents: int) -> str:
    whole, part = divmod(cents, 100)
    return str(whole) if part == 0 else f"{whole},{part:02d}"


def _render(request: Request, template: str, **context: Any) -> Response:
    templates: Jinja2Templates = request.app.state.templates
    return templates.TemplateResponse(request, template, context)


@router.get("/")
def index(
    request: Request,
    max_bd: str | None = Query(default=None),
    max_4k: str | None = Query(default=None),
    format: str | None = Query(default=None),
    store: str | None = Query(default=None),
    condition: str | None = Query(default=None),
    q: str | None = Query(default=None),
) -> Response:
    filters = queries.Filters(
        max_bd_cents=_euros_to_cents(max_bd, queries.MAX_BD_CENTS),
        max_4k_cents=_euros_to_cents(max_4k, queries.MAX_4K_CENTS),
        format=format if format in FORMATS else None,
        store=store or None,
        condition=condition if condition in CONDITIONS else None,
        q=q.strip() if q and q.strip() else None,
    )
    page = queries.main_page(_engine(request), filters)
    return _render(
        request,
        "index.html",
        page=page,
        max_bd_display=_display_euros(filters.max_bd_cents),
        max_4k_display=_display_euros(filters.max_4k_cents),
    )


@router.get("/ignored")
def ignored(request: Request) -> Response:
    return _render(request, "ignored.html", rows=queries.ignored_page(_engine(request)))


@router.get("/queue")
def queue(request: Request) -> Response:
    items = queries.match_queue(_engine(request))
    return _render(request, "queue.html", items=items, has_tmdb=_tmdb_client(request) is not None)


@router.get("/match")
def match_alias() -> Response:
    return RedirectResponse("/queue", status_code=307)


@router.get("/watchlist")
def watchlist(request: Request) -> Response:
    return _render(request, "watchlist.html", entries=queries.watchlist_page(_engine(request)))


@router.get("/products/{store_product_id}")
def product(request: Request, store_product_id: int) -> Response:
    result = queries.product_history(_engine(request), store_product_id)
    if result is None:
        raise HTTPException(404, "No such product")
    row, history = result
    return _render(request, "product.html", row=row, history=history)


@router.get("/status")
def status(request: Request) -> Response:
    return _render(
        request,
        "status.html",
        stores=queries.status_page(_engine(request)),
        freshness_hours=queries.FRESHNESS_HOURS,
        max_bd_cents=queries.MAX_BD_CENTS,
        max_4k_cents=queries.MAX_4K_CENTS,
    )


@router.post("/api/v2/products/{store_product_id}/match")
async def product_match(request: Request, store_product_id: int) -> JSONResponse:
    body = await request.json()
    tmdb_id = body.get("tmdb_id") if isinstance(body, dict) else None
    if tmdb_id is not None and not isinstance(tmdb_id, int):
        raise HTTPException(400, "tmdb_id must be an integer or null")
    try:
        state = set_manual_match(_engine(request), _tmdb_client(request), store_product_id, tmdb_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except TmdbError as error:
        raise HTTPException(502, str(error)) from error
    return JSONResponse({"status": state.status, "tmdb_id": state.tmdb_id})


@router.post("/api/v2/products/{store_product_id}/{action}")
def product_action(request: Request, store_product_id: int, action: str) -> JSONResponse:
    if action not in ACTIONS:
        raise HTTPException(404, f"Unknown action {action!r}")
    try:
        result = preferences.apply(_engine(request), store_product_id, action)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    return JSONResponse(result)


@router.get("/api/v2/tmdb/search")
def tmdb_search(request: Request, q: str, year: int | None = None) -> JSONResponse:
    client = _tmdb_client(request)
    if client is None:
        raise HTTPException(503, "TMDB_API_KEY is not configured")
    try:
        candidates = client.search_movies(q, year)
    except TmdbError as error:
        raise HTTPException(502, str(error)) from error
    return JSONResponse(
        [
            {
                "tmdb_id": c.tmdb_id,
                "title": c.title,
                "original_title": c.original_title,
                "release_year": c.release_year,
                "poster_path": c.poster_path,
            }
            for c in candidates
        ]
    )
