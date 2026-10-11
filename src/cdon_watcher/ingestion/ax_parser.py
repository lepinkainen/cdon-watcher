"""Offline parser for saved Levykauppa Äx offer listing pages."""

import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from ..box_set_detector import is_box_set
from .contract import Availability, Condition, Format, ParsedProduct, ParseError

PARSER_VERSION = "ax-1"
BASE_URL = "https://www.levykauppax.fi/"

_USED_PREFIX = re.compile(r"^\s*käytetty\s+", re.IGNORECASE)
_DISC_COUNT = re.compile(r"^\s*(\d+)\s*(?:x\s*)?(?=blu|dvd|ultra|4k|uhd)", re.IGNORECASE)
_UHD = re.compile(r"4k|ultra\s*hd|uhd", re.IGNORECASE)
_BLURAY = re.compile(r"blu", re.IGNORECASE)
_DVD = re.compile(r"dvd", re.IGNORECASE)
_QUANTITY = re.compile(r"(\d+)\s*kpl", re.IGNORECASE)
_YEAR = re.compile(r"\b(19\d{2}|20\d{2})\b")
_EDITION_TAG = re.compile(
    r"\s*[(\[][^()\[\]]*(blu-?ray|4k|uhd|dvd|steelbook|limited|edition|remaster)[^()\[\]]*[)\]]",
    re.IGNORECASE,
)
_WHITESPACE = re.compile(r"\s+")


def parse_price_cents(text: str) -> int | None:
    """Turn a localized price such as '1 234,56 €' into integer cents."""
    cleaned = re.sub(r"[^\d,.]", "", text.replace("\xa0", ""))
    if not cleaned:
        return None
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    if value <= 0 or value != value.quantize(Decimal("0.01")):
        return None
    return int(value * 100)


def parse_format(raw: str) -> tuple[Format, Condition, int | None]:
    """Split Äx media text ('Käytetty 2 Blu-ray', '3x4K Ultra HD') into parts."""
    condition = Condition.USED if _USED_PREFIX.match(raw) else Condition.NEW
    rest = _USED_PREFIX.sub("", raw)
    count_match = _DISC_COUNT.match(rest)
    disc_count = int(count_match.group(1)) if count_match else None
    if _UHD.search(rest):
        media = Format.UHD
    elif _BLURAY.search(rest):
        media = Format.BLURAY
    elif _DVD.search(rest):
        media = Format.DVD
    else:
        media = Format.UNKNOWN
    return media, condition, disc_count


def parse_availability(node: Tag | None) -> tuple[Availability, str | None]:
    if node is None:
        return Availability.UNKNOWN, None
    text = node.get_text(" ", strip=True)
    lowered = text.lower()
    classes = node.get("class") or []
    if "in-stock" in classes or lowered.startswith("tuotetta hyllyssä"):
        return Availability.IN_STOCK, text
    if "ennakko" in lowered:
        return Availability.PREORDER, text
    if "loppu" in lowered:
        return Availability.OUT_OF_STOCK, text
    if lowered.startswith("toimitusaika n"):
        return Availability.SUPPLIER_ORDER, text
    return Availability.UNKNOWN, text or None


def clean_title(raw: str) -> str:
    cleaned = _EDITION_TAG.sub("", raw)
    return _WHITESPACE.sub(" ", cleaned).strip(" -–:") or raw.strip()


class AxParser:
    store = "ax"
    version = PARSER_VERSION

    def parse(self, body: bytes) -> tuple[list[ParsedProduct], list[ParseError]]:
        soup = BeautifulSoup(body, "html.parser")
        rows = soup.select("ul.list-products > li.hproduct")
        if not rows:
            return [], [ParseError(product_id=None, reason="No offer rows in page")]
        products: list[ParsedProduct] = []
        errors: list[ParseError] = []
        for row in rows:
            product_id = str(row.get("id", "")).removeprefix("p-") or None
            try:
                products.append(self._row(row, product_id))
            except ValueError as error:
                errors.append(ParseError(product_id=product_id, reason=str(error)))
        return products, errors

    def _row(self, row: Tag, product_id: str | None) -> ParsedProduct:
        if product_id is None or not product_id.isdecimal():
            raise ValueError("Row has no numeric product id")
        link = row.select_one("a.fn[href]")
        if link is None:
            raise ValueError("Row has no title link")
        raw_title = link.get_text(" ", strip=True)
        if not raw_title:
            raise ValueError("Row has an empty title")
        media = row.select_one("span.type")
        if media is None:
            raise ValueError("Row has no media type")
        format_raw = media.get_text(" ", strip=True)
        fmt, condition, disc_count = parse_format(format_raw)
        price_cents, regular_cents = _prices(row)
        availability, availability_raw = parse_availability(row.select_one("p.shipping"))
        details = _details(row)
        note = row.select_one(".description")

        return ParsedProduct(
            store=self.store,
            product_id=product_id,
            raw_title=raw_title,
            cleaned_title=clean_title(raw_title),
            edition_url=urljoin(BASE_URL, str(link["href"])),
            format=fmt,
            format_raw=format_raw,
            disc_count=disc_count,
            condition=condition,
            condition_raw="Käytetty" if condition is Condition.USED else None,
            availability=availability,
            availability_raw=availability_raw,
            stock_quantity=_quantity(row),
            price_cents=price_cents,
            regular_price_cents=regular_cents,
            release_year=_year(details.get("Julkaisuvuosi", "")),
            publisher=details.get("Yhtiö") or None,
            edition_note=note.get_text(" ", strip=True) if note is not None else None,
            image_url=_image_url(row),
            is_collection=is_box_set(raw_title),
        )


def _prices(row: Tag) -> tuple[int, int | None]:
    price_node = row.select_one("span.price")
    if price_node is None:
        raise ValueError("Row has no price")
    regular_node = price_node.select_one("del")
    regular_cents = None
    if regular_node is not None:
        regular_cents = parse_price_cents(regular_node.get_text())
        regular_node.extract()
    price_cents = parse_price_cents(price_node.get_text())
    if price_cents is None:
        raise ValueError("Row has an invalid current price")
    if regular_cents is not None and regular_cents < price_cents:
        raise ValueError("Regular price is below the current price")
    return price_cents, regular_cents


def _quantity(row: Tag) -> int | None:
    sticker = row.select_one(".sticker-bottom-right")
    if sticker is None:
        return None
    match = _QUANTITY.search(sticker.get_text())
    return int(match.group(1)) if match else None


def _details(row: Tag) -> dict[str, str]:
    details: dict[str, str] = {}
    for term in row.select("dl dt"):
        value = term.find_next_sibling("dd")
        if value is not None:
            details[term.get_text(strip=True)] = value.get_text(" ", strip=True)
    return details


def _year(text: str) -> int | None:
    match = _YEAR.search(text)
    return int(match.group(1)) if match else None


def _image_url(row: Tag) -> str | None:
    image = row.select_one("img.photo")
    if image is None:
        return None
    source = image.get("data-src") or image.get("src")
    return urljoin(BASE_URL, str(source)) if source else None
