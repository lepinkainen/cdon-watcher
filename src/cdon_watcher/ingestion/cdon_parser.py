"""Offline parser for saved CDON category listing pages (rendered HTML)."""

import re
from typing import Any
from urllib.parse import urljoin

from ..box_set_detector import is_box_set
from .contract import Availability, Condition, ParsedProduct, ParseError
from .normalize import amount_to_cents, clean_title
from .stores import cdon_article_format, cdon_article_media, cdon_articles

PARSER_VERSION = "cdon-1"
BASE_URL = "https://cdon.fi/"


def _condition(article: dict[str, Any]) -> tuple[Condition, str | None]:
    for item in article.get("classifications") or []:
        if isinstance(item, dict) and item.get("name") == "condition":
            raw = str(item.get("value") or "")
            lowered = raw.lower()
            if lowered == "new":
                return Condition.NEW, raw
            if lowered in {"used", "refurbished"}:
                return Condition.USED, raw
            return Condition.UNKNOWN, raw
    return Condition.UNKNOWN, None


def _availability(article: dict[str, Any]) -> tuple[Availability, str | None]:
    publish_state = article.get("publishState")
    stock = article.get("stock")
    raw = f"publishState={publish_state} stock={stock}"
    if publish_state != "published" or not isinstance(stock, int):
        return Availability.UNKNOWN, raw
    if stock > 0:
        return Availability.IN_STOCK, raw
    return Availability.OUT_OF_STOCK, raw


class CdonParser:
    store = "cdon"
    version = PARSER_VERSION
    expires_unseen = False

    def parse(self, body: bytes) -> tuple[list[ParsedProduct], list[ParseError]]:
        try:
            articles = cdon_articles(body)
        except ValueError as error:
            return [], [ParseError(product_id=None, reason=str(error))]
        products: list[ParsedProduct] = []
        errors: list[ParseError] = []
        for article in articles:
            slug = str(article.get("slug") or "")
            product_id = slug[-16:] if re.fullmatch(r".*[0-9a-f]{16}", slug) else None
            try:
                products.append(self._article(article, slug, product_id))
            except (ValueError, TypeError) as error:
                errors.append(ParseError(product_id=product_id, reason=str(error)))
        return products, errors

    def _article(self, article: dict[str, Any], slug: str, product_id: str | None) -> ParsedProduct:
        if product_id is None:
            raise ValueError(f"Article without a 16-hex id slug: {slug!r}")
        raw_title = str(article.get("title") or "").strip()
        if not raw_title:
            raise ValueError("Article has an empty title")
        price = article.get("price") or {}
        amount = price.get("amount")
        price_cents = amount_to_cents(amount) if isinstance(amount, int | float) else None
        if price_cents is None:
            raise ValueError("Article has an invalid price")
        currency = str(price.get("currency") or "EUR")
        format_raw = cdon_article_format(article)
        fmt = cdon_article_media(article)
        condition, condition_raw = _condition(article)
        availability, availability_raw = _availability(article)
        stock = article.get("stock")
        images = article.get("images") or []
        image_url = None
        if images and isinstance(images[0], dict) and images[0].get("url"):
            image_url = str(images[0]["url"])
        return ParsedProduct(
            store=self.store,
            product_id=product_id,
            raw_title=raw_title,
            cleaned_title=clean_title(raw_title),
            edition_url=urljoin(BASE_URL, f"/tuote/{slug}/"),
            format=fmt,
            format_raw=format_raw,
            condition=condition,
            condition_raw=condition_raw,
            availability=availability,
            availability_raw=availability_raw,
            stock_quantity=stock if isinstance(stock, int) and stock >= 0 else None,
            price_cents=price_cents,
            currency=currency,
            image_url=image_url,
            is_collection=is_box_set(raw_title),
        )
