"""Store-independent normalization helpers shared by parsers."""

import re
from decimal import Decimal, InvalidOperation

from .contract import Format

_EDITION_TAG = re.compile(
    r"\s*[(\[][^()\[\]]*(blu-?ray|4k|uhd|dvd|steelbook|limited|edition|remaster)[^()\[\]]*[)\]]",
    re.IGNORECASE,
)
_TRAILING_FORMAT = re.compile(
    r"(\s*[-–:]?\s*(\d+\s*x?\s*)?(4k\s*(ultra\s*hd|uhd)?|uhd|blu[\s-]?ray|dvd|steelbook))+\s*$",
    re.IGNORECASE,
)
_WHITESPACE = re.compile(r"\s+")
_UHD = re.compile(r"4k|ultra\s*hd|uhd", re.IGNORECASE)
_BLURAY = re.compile(r"blu[\s_-]?ray|\bbd\b", re.IGNORECASE)
_DVD = re.compile(r"dvd", re.IGNORECASE)


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
    return amount_to_cents(value)


def amount_to_cents(value: Decimal | float | int) -> int | None:
    """Exact decimal amount to positive integer cents, or None when invalid."""
    try:
        decimal_value = Decimal(str(value))
    except InvalidOperation:
        return None
    if decimal_value <= 0 or decimal_value != decimal_value.quantize(Decimal("0.01")):
        return None
    return int(decimal_value * 100)


def format_from_text(text: str) -> Format:
    """Detect the media format from free text such as a media label or URL slug."""
    if _UHD.search(text):
        return Format.UHD
    if _BLURAY.search(text):
        return Format.BLURAY
    if _DVD.search(text):
        return Format.DVD
    return Format.UNKNOWN


def clean_title(raw: str) -> str:
    """Strip bracketed and trailing format/edition markers for matching."""
    cleaned = _EDITION_TAG.sub("", raw)
    cleaned = _TRAILING_FORMAT.sub("", cleaned)
    cleaned = _WHITESPACE.sub(" ", cleaned).strip(" -–:")
    return cleaned or raw.strip()
