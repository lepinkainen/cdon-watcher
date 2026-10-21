"""Jinja2 filters for the catalog templates."""

from datetime import datetime

from fastapi.templating import Jinja2Templates


def euros(cents: int | None) -> str:
    if cents is None:
        return ""
    whole, part = divmod(cents, 100)
    return f"{whole},{part:02d} €"


def when(value: datetime | None) -> str:
    if value is None:
        return "never"
    return value.strftime("%Y-%m-%d %H:%M")


def register_filters(templates: Jinja2Templates) -> None:
    templates.env.filters["euros"] = euros
    templates.env.filters["when"] = when
