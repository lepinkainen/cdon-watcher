"""MyMovies (mymovies.fi) transport and result reading, shared by crawl and search.

The product search at /tuotteet.php is an empty shell; its script POSTs the
filter form to /ajax/hae-tuotteet2.php, which returns JSON with the result cards
as HTML. Both the catalogue crawl (empty query, in stock only) and the wishlist
searches (a title, any availability) go through that endpoint.

The archive records requests as /tuotteet.php URLs carrying the parameters that
vary (q, saatavuus, page); MyMoviesFetcher turns one into the POST. The other
filters are fixed: Blu-ray and 4K UHD only (no DVD), new and used, both price
kinds, all product types, title search only.

The site answers 403 to non-browser User-Agents, so this fetcher identifies as
desktop Chrome.
"""

import json
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlsplit

import requests
from bs4 import BeautifulSoup, Tag

from .archive import Discovery
from .crawler import Response
from .stores import Listing

BASE_URL = "https://www.mymovies.fi/"
SEARCH_PAGE = "https://www.mymovies.fi/tuotteet.php"
AJAX_URL = "https://www.mymovies.fi/ajax/hae-tuotteet2.php"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

IN_STOCK_ONLY = "1"
ANY_AVAILABILITY = "0"

FIXED_FIELDS: list[tuple[str, str]] = [
    ("tyyppi", "3"),  # all types: box sets are kept and shown as collections
    ("formaatti[]", "2"),  # Blu-ray
    ("formaatti[]", "3"),  # 4K UHD; DVD (1) is left out
    ("saldo[]", "0"),  # new
    ("saldo[]", "1"),  # used
    ("kiintea[]", "0"),  # "Tarjous": not fixed price, not a discount marker
    ("kiintea[]", "1"),  # "Kiinteä hinta": fixed price
    ("jarjestys", "muokattu"),
    ("hakukentta", "elokuva"),  # title only; "kaikki" also matches cast and crew
]

NO_RESULTS = "Ei tuloksia"
_PAGE = re.compile(r'data-page="(\d+)"')


def page_url(query: str, availability: str, page: int = 1) -> str:
    """The archived request URL for one results page."""
    params = {"q": query, "saatavuus": availability}
    if page != 1:
        params["page"] = str(page)
    return f"{SEARCH_PAGE}?{urlencode(params)}"


@dataclass(frozen=True)
class Request:
    query: str
    availability: str
    page: int


def parse_url(url: str) -> Request:
    """Read an archived request URL; raises ValueError outside the search page."""
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "www.mymovies.fi"
        or parsed.path != "/tuotteet.php"
        or parsed.fragment
    ):
        raise ValueError(f"URL outside the MyMovies search: {url}")
    query = parse_qs(parsed.query, keep_blank_values=True)
    if not set(query) <= {"q", "saatavuus", "page"} or any(len(v) != 1 for v in query.values()):
        raise ValueError(f"Unexpected search parameters: {url}")
    availability = query.get("saatavuus", [""])[0]
    if availability not in {IN_STOCK_ONLY, ANY_AVAILABILITY}:
        raise ValueError(f"Invalid availability filter: {url}")
    page = int(query.get("page", ["1"])[0])
    if not 1 <= page <= 1000:
        raise ValueError(f"Invalid or excessive page number: {page}")
    return Request(query.get("q", [""])[0], availability, page)


def form_fields(request: Request) -> list[tuple[str, str]]:
    return [
        ("q", request.query),
        ("saatavuus", request.availability),
        *FIXED_FIELDS,
        ("page", str(request.page)),
    ]


class MyMoviesFetcher:
    """POSTs the search form for an archived /tuotteet.php URL.

    The response is returned under the requested URL: the POST target never
    changes, and redirects are not followed.
    """

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT

    def __call__(self, url: str) -> Response:
        fields = form_fields(parse_url(url))
        response = self.session.post(
            AJAX_URL,
            files=[(name, (None, value)) for name, value in fields],
            timeout=30,
            allow_redirects=False,
        )
        return Response(url, response.status_code, response.content)

    def search(self, url: str) -> Response:
        return self(url)

    def close(self) -> None:
        self.session.close()


@dataclass
class Results:
    cards: list[Tag]
    total: int
    last_page: int
    """Highest page the paginator links to; 0 when there is no paginator."""
    active_page: int | None


def read_results(body: bytes) -> Results:
    """Parse an AJAX response. Raises ValueError when it is not a results response."""
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError) as error:
        raise ValueError(f"Not a JSON search response: {error}") from error
    if not isinstance(data, dict) or not isinstance(data.get("html"), str):
        raise ValueError("Search response has no result HTML")
    if data.get("error"):
        raise ValueError(f"Search error: {data['error']}")
    total = data.get("total")
    if not isinstance(total, int):
        raise ValueError("Search response has no result total")
    soup = BeautifulSoup(data["html"], "html.parser")
    cards = [c for c in soup.select("div.col > div.card") if isinstance(c, Tag)]
    if not cards and total and NO_RESULTS not in data["html"]:
        raise ValueError("Unrecognized result HTML")
    pagination = str(data.get("pagination") or "")
    pages = [int(p) for p in _PAGE.findall(pagination)]
    active = BeautifulSoup(pagination, "html.parser").select_one(".sivu-linkki.btn-primary")
    active_page = int(str(active["data-page"])) if active is not None else None
    return Results(cards, total, max(pages, default=0), active_page)


def card_id(card: Tag) -> str:
    link = card.select_one('a[href*="tuotetiedot.php?id="]')
    match = re.search(r"tuotetiedot\.php\?id=(\d+)", str(link["href"])) if link else None
    if match is None:
        raise ValueError("Card has no product link")
    return match.group(1)


def edition_url(product_id: str) -> str:
    return f"{BASE_URL}tuotetiedot.php?id={product_id}"


class MyMoviesAdapter:
    """Every in-stock Blu-ray and 4K UHD product: the empty search, 60 per page.

    A complete run lists the whole in-stock catalogue, so products it no longer
    sees have sold out.
    """

    key = "mymovies"
    scope = "in-stock"
    start_url = page_url("", IN_STOCK_ONLY)
    start_urls = (start_url,)
    expires_unseen = True

    def page_number(self, url: str) -> int:
        request = parse_url(url)
        if request.query or request.availability != IN_STOCK_ONLY:
            raise ValueError(f"URL outside the in-stock listing: {url}")
        return request.page

    def discover(self, body: bytes, requested_url: str, final_url: str) -> Listing:
        page = self.page_number(requested_url)
        if self.page_number(final_url) != page:
            raise ValueError("Pagination redirected to a different page")
        results = read_results(body)
        if not results.cards:
            raise ValueError("Empty listing page")
        if results.active_page is not None and results.active_page != page:
            raise ValueError("Pagination loop: active page differs from requested page")
        ids = [card_id(card) for card in results.cards]
        products = [Discovery(product_id=i, edition_url=edition_url(i)) for i in ids]
        pages = [page_url("", IN_STOCK_ONLY, n) for n in range(1, max(results.last_page, page) + 1)]
        return Listing(products=products, pages=pages, signature=tuple(sorted(ids)))
