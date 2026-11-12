"""Offline parser for saved MyMovies search responses (crawl pages and searches).

A result card shows a new and a used price, each with its own stock state, so
one card becomes up to two products: '<id>:new' and '<id>:used', sharing the
product page URL. A condition without a price line is not offered at all.

Stock comes from the buy button's data-uusi / data-kaytetty flags (1 = in
stock); a card with nothing in stock has no button. The coloured dot before
each price agrees with the flags (red = out of stock, green or yellow = in
stock) and is kept as the raw availability text.
"""

import re
from typing import Any
from urllib.parse import urljoin

from bs4 import Tag

from ..box_set_detector import is_box_set
from .contract import Availability, Condition, ParsedProduct, ParseError
from .mymovies import BASE_URL, card_id, edition_url, read_results
from .normalize import clean_title, format_from_text, parse_price_cents

PARSER_VERSION = "mymovies-1"

FIXED_PRICE_BADGE = "Kiinteä hinta"
_CONDITIONS = {
    "Uusi": (Condition.NEW, "data-uusi"),
    "Käytetty": (Condition.USED, "data-kaytetty"),
}
_PRICE_LINE = re.compile(r"^\s*(Uusi|Käytetty)\s*:\s*(.+)$")
_DOT_COLOUR = re.compile(r"background:\s*(#[0-9a-fA-F]{3,6})")
_YEAR = re.compile(r"^\((\d{4})\)$")


class MyMoviesParser:
    store = "mymovies"
    version = PARSER_VERSION
    expires_unseen = True

    def parse(self, body: bytes) -> tuple[list[ParsedProduct], list[ParseError]]:
        try:
            results = read_results(body)
        except ValueError as error:
            return [], [ParseError(product_id=None, reason=str(error))]
        if not results.cards:
            return [], [ParseError(product_id=None, reason="No products in listing page")]
        return self._cards(results.cards)

    def parse_search(self, body: bytes) -> tuple[list[ParsedProduct], list[ParseError]]:
        """A search response; no results is a valid, empty answer."""
        try:
            results = read_results(body)
        except ValueError as error:
            return [], [ParseError(product_id=None, reason=str(error))]
        return self._cards(results.cards)

    def _cards(self, cards: list[Tag]) -> tuple[list[ParsedProduct], list[ParseError]]:
        products: list[ParsedProduct] = []
        errors: list[ParseError] = []
        for card in cards:
            product_id: str | None = None
            try:
                product_id = card_id(card)
                products.extend(self._card(card, product_id))
            except ValueError as error:
                errors.append(ParseError(product_id=product_id, reason=str(error)))
        return products, errors

    def _card(self, card: Tag, product_id: str) -> list[ParsedProduct]:
        title_node = card.select_one(".tuote-nimi")
        raw_title = title_node.get_text(" ", strip=True) if title_node is not None else ""
        if not raw_title:
            raise ValueError("Card has no title")
        badges = [b.get_text(" ", strip=True) for b in card.select(".card-body span.badge")]
        if not badges:
            raise ValueError("Card has no format badge")
        format_raw = badges[0]
        offers = _offers(card)
        if not offers:
            raise ValueError("Card has no prices")
        button = card.select_one("button.osta-nappi")
        image = card.select_one("img.card-img-top[src]")
        common: dict[str, Any] = {
            "store": self.store,
            "raw_title": raw_title,
            "cleaned_title": clean_title(raw_title),
            "edition_url": edition_url(product_id),
            "format": format_from_text(format_raw),
            "format_raw": format_raw,
            "release_year": _year(card),
            "edition_note": FIXED_PRICE_BADGE if FIXED_PRICE_BADGE in badges[1:] else None,
            "image_url": urljoin(BASE_URL, str(image["src"])) if image is not None else None,
            "is_collection": is_box_set(raw_title),
        }
        products = []
        for label, price_cents, colour in offers:
            condition, flag = _CONDITIONS[label]
            in_stock = button is not None and button.get(flag) == "1"
            products.append(
                ParsedProduct(
                    product_id=f"{product_id}:{condition.value}",
                    condition=condition,
                    condition_raw=label,
                    price_cents=price_cents,
                    availability=Availability.IN_STOCK if in_stock else Availability.OUT_OF_STOCK,
                    availability_raw=colour,
                    **common,
                )
            )
        return products


def _offers(card: Tag) -> list[tuple[str, int, str | None]]:
    """(condition label, price, dot colour) for each price line on the card."""
    offers = []
    for line in card.select(".tuote-hinnat > div"):
        match = _PRICE_LINE.match(line.get_text(" ", strip=True))
        if match is None or not re.search(r"\d", match.group(2)):
            continue  # 'Uusi: -': the condition is not offered
        price = parse_price_cents(match.group(2))
        if price is None:
            raise ValueError(f"Invalid {match.group(1)} price: {match.group(2)!r}")
        dot = line.select_one("span[style]")
        colour = _DOT_COLOUR.search(str(dot["style"])) if dot is not None else None
        offers.append((match.group(1), price, colour.group(1).lower() if colour else None))
    return offers


def _year(card: Tag) -> int | None:
    for small in card.select(".tuote-hinnat small"):
        match = _YEAR.match(small.get_text(strip=True))
        if match:
            return int(match.group(1))
    return None
