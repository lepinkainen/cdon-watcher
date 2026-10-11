"""Shared product contract produced by every store parser.

Parsers return these records from saved responses only. They perform no HTTP
requests, no database writes, and no TMDB calls.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Format(StrEnum):
    BLURAY = "bd"
    UHD = "4k"
    DVD = "dvd"
    UNKNOWN = "unknown"


class Condition(StrEnum):
    NEW = "new"
    USED = "used"
    UNKNOWN = "unknown"


class Availability(StrEnum):
    """Only IN_STOCK counts as confirmed stock for the shopping UI."""

    IN_STOCK = "in_stock"
    SUPPLIER_ORDER = "supplier_order"
    PREORDER = "preorder"
    OUT_OF_STOCK = "out_of_stock"
    UNKNOWN = "unknown"


ELIGIBLE_FORMATS = frozenset({Format.BLURAY, Format.UHD})


class ParsedProduct(BaseModel):
    """One store edition as observed in one saved response."""

    store: str
    product_id: str
    raw_title: str
    cleaned_title: str
    edition_url: str
    format: Format
    format_raw: str
    disc_count: int | None = None
    condition: Condition
    condition_raw: str | None = None
    availability: Availability
    availability_raw: str | None = None
    stock_quantity: int | None = None
    price_cents: int = Field(gt=0)
    regular_price_cents: int | None = Field(default=None, gt=0)
    currency: str = "EUR"
    release_year: int | None = None
    publisher: str | None = None
    edition_note: str | None = None
    image_url: str | None = None
    is_collection: bool = False

    @property
    def eligible(self) -> bool:
        return self.format in ELIGIBLE_FORMATS


class ParseError(BaseModel):
    """A row or page the parser could not turn into a product. Never fatal."""

    product_id: str | None
    reason: str


class ParsedSnapshot(BaseModel):
    snapshot_id: int
    requested_url: str
    fetched_at: datetime
    products: list[ParsedProduct] = Field(default_factory=list)
    errors: list[ParseError] = Field(default_factory=list)


class ParsedRun(BaseModel):
    """Output of the offline parse stage for one archived run."""

    store: str
    run_id: int
    parser_version: str
    complete: bool
    parsed_at: datetime
    expire_unseen: bool = True
    """Whether a complete run of this store means unseen products left the scope."""
    snapshots: list[ParsedSnapshot] = Field(default_factory=list)

    @property
    def products(self) -> list[ParsedProduct]:
        return [p for s in self.snapshots for p in s.products]

    @property
    def errors(self) -> list[ParseError]:
        return [e for s in self.snapshots for e in s.errors]
