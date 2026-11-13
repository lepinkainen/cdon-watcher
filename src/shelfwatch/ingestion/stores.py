"""Store-specific discovery. No normalized products or database writes."""

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup

from .archive import Discovery
from .contract import ELIGIBLE_FORMATS, Format
from .normalize import format_from_text


@dataclass
class Listing:
    products: list[Discovery]
    pages: list[str]
    signature: tuple[str, ...]


class StoreAdapter(Protocol):
    key: str
    scope: str
    start_urls: tuple[str, ...]
    """Listing pages that seed the crawl; discover() returns the rest."""
    expires_unseen: bool
    """Whether a complete run proves that unseen products left the store scope."""

    def discover(self, body: bytes, requested_url: str, final_url: str) -> Listing: ...


class AxAdapter:
    """Offer category of levykauppax.fi, one cheapest-first pass per format filter.

    The unfiltered offer listing mixes DVDs and grows to hundreds of pages during
    storewide sales, so each pass narrows it with a format filter (`f2`) sorted
    by price (`o2=p`) and stops after `max_pages`. Expensive offers past the cap
    are not crawled, and a complete run expires them from the category.
    """

    key = "ax"
    scope = "movie-offers"
    base_url = "https://www.levykauppax.fi/leffat/offer/"
    # Format filter -> listing heading, which also tells an error page apart.
    passes = {
        "blu": "Elokuvat - Blu-Ray",
        "uhd": "Elokuvat - 4K Ultra HD",
        "ultrasb": "Elokuvat - 4K UHD Steelbook",
        "blusb": "Elokuvat - Blu-Ray Steelbook",
    }
    expires_unseen = True

    def __init__(self, max_pages: int = 10) -> None:
        if max_pages < 1:
            raise ValueError("max_pages must be at least 1")
        self.max_pages = max_pages
        self.start_urls = tuple(self.page_url(f, 1) for f in self.passes)

    def page_url(self, media_filter: str, page: int) -> str:
        query = f"f2={media_filter}&o2=p"
        return f"{self.base_url}?{query}" if page == 1 else f"{self.base_url}?p2={page}&{query}"

    def page_number(self, url: str) -> tuple[str, int]:
        """Format filter and page number of an offer listing URL."""
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "www.levykauppax.fi"
            or parsed.path != "/leffat/offer/"
            or parsed.fragment
        ):
            raise ValueError(f"URL outside offer scope: {url}")
        query = parse_qs(parsed.query, keep_blank_values=True)
        if (
            not {"f2", "o2"} <= set(query) <= {"f2", "o2", "p2"}
            or any(len(values) != 1 for values in query.values())
            or query["f2"][0] not in self.passes
            or query["o2"][0] != "p"
        ):
            raise ValueError(f"Unexpected listing query: {url}")
        page = int(query.get("p2", ["1"])[0])
        if not 1 <= page <= 1000:
            raise ValueError(f"Invalid or excessive page number: {page}")
        return query["f2"][0], page

    def discover(self, body: bytes, requested_url: str, final_url: str) -> Listing:
        media_filter, page = self.page_number(requested_url)
        if self.page_number(final_url) != (media_filter, page):
            raise ValueError("Pagination redirected to a different page")
        soup = BeautifulSoup(body, "html.parser")
        heading = soup.select_one("h1")
        # Filtered pages 1-2 name the format; from page 3 on Äx shows the generic heading.
        allowed = {self.passes[media_filter], "Elokuvat - Tarjoukset"}
        if heading is None or heading.get_text(" ", strip=True) not in allowed:
            raise ValueError("Missing movie offer heading; possible error page")
        active = soup.select_one(".pagination .active")
        if active is not None and active.get_text(strip=True) != str(page):
            raise ValueError("Pagination loop: active page differs from requested page")
        rows = soup.select("ul.list-products > li.hproduct")
        if not rows:
            raise ValueError("Empty or unrecognized offer listing")
        products, ids = self._rows(rows)
        last_page = page
        for link in soup.select(".pagination a[href]"):
            linked_filter, linked_page = self.page_number(urljoin(self.base_url, str(link["href"])))
            if linked_filter != media_filter:
                raise ValueError(f"Pagination left the {media_filter} filter")
            last_page = max(last_page, linked_page)
        # Fetch intermediate pages even if the paginator abbreviates them with an ellipsis.
        pages = [
            self.page_url(media_filter, n) for n in range(1, min(last_page, self.max_pages) + 1)
        ]
        return Listing(products=products, pages=pages, signature=tuple(sorted(ids)))

    def _rows(self, rows: list[Any]) -> tuple[list[Discovery], list[str]]:
        products = []
        ids = []
        for row in rows:
            product_id = str(row.get("id", "")).removeprefix("p-")
            link = row.select_one("a.fn[href]")
            media = row.select_one("span.type")
            if not product_id.isdecimal() or link is None or media is None:
                raise ValueError("Offer row lacks an edition ID, title link, or format")
            ids.append(product_id)
            edition_url = urljoin(self.base_url, str(link["href"]))
            parsed = urlsplit(edition_url)
            if (
                parsed.scheme != "https"
                or parsed.netloc != "www.levykauppax.fi"
                or not parsed.path.startswith("/movie/")
                or parsed.fragment != product_id
            ):
                raise ValueError(f"Invalid edition link for {product_id}")
            if re.search(r"blu|4k|ultra\s*hd|uhd", media.get_text(), re.IGNORECASE):
                products.append(Discovery(product_id=product_id, edition_url=edition_url))
        return products, ids


def next_data(body: bytes) -> dict[str, Any]:
    """Return the parsed Next.js page state embedded in a CDON page."""
    soup = BeautifulSoup(body, "html.parser")
    node = soup.select_one("script#__NEXT_DATA__")
    if node is None:
        raise ValueError("Missing __NEXT_DATA__; possible challenge or error page")
    try:
        data = json.loads(node.get_text())
    except json.JSONDecodeError as error:
        raise ValueError("Malformed __NEXT_DATA__") from error
    if not isinstance(data, dict):
        raise ValueError("Unexpected __NEXT_DATA__ shape")
    return data


def cdon_articles(body: bytes) -> list[dict[str, Any]]:
    """Articles of a CDON category listing page, validated for shape."""
    props = next_data(body).get("props", {}).get("pageProps", {})
    if props.get("pageName") != "CategoryPage":
        raise ValueError(f"Not a category page: {props.get('pageName')!r}")
    articles = props.get("serverData", {}).get("articles")
    if not isinstance(articles, list) or not articles:
        raise ValueError("Empty or unrecognized category listing")
    return [a for a in articles if isinstance(a, dict)]


def cdon_article_format(article: dict[str, Any]) -> str:
    """Media format text for an article: the preset property, else the URL slug."""
    for prop in article.get("properties") or []:
        if isinstance(prop, dict) and prop.get("name") == "preset_media_format":
            return str(prop.get("value") or "")
    return str(article.get("slug") or "")


def cdon_article_media(article: dict[str, Any]) -> Format:
    """Normalized format: preset property first, then slug and title text."""
    media = format_from_text(cdon_article_format(article))
    if media is Format.UNKNOWN:
        media = format_from_text(f"{article.get('slug') or ''} {article.get('title') or ''}")
    return media


class CdonAdapter:
    """First N pages of cdon.fi/elokuvat/, rendered in a browser.

    CDON sits behind a Cloudflare challenge and renders listings client-side,
    so listing bodies are post-JavaScript HTML. The page state carries price,
    stock, format and URL for every article, so no product pages are fetched.
    """

    key = "cdon"
    scope = "elokuvat"
    start_url = "https://cdon.fi/elokuvat/"
    start_urls = (start_url,)
    expires_unseen = False

    def __init__(self, max_pages: int = 10) -> None:
        if max_pages < 1:
            raise ValueError("max_pages must be at least 1")
        self.max_pages = max_pages

    def page_url(self, page: int) -> str:
        return self.start_url if page == 1 else f"{self.start_url}?page={page}"

    def page_number(self, url: str) -> int:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "cdon.fi"
            or parsed.path != "/elokuvat/"
            or parsed.fragment
        ):
            raise ValueError(f"URL outside category scope: {url}")
        query = parse_qs(parsed.query, keep_blank_values=True)
        if query and (set(query) != {"page"} or len(query["page"]) != 1):
            raise ValueError(f"Unexpected pagination query: {url}")
        page = int(query.get("page", ["1"])[0])
        if not 1 <= page <= 10000:
            raise ValueError(f"Invalid page number: {page}")
        return page

    def discover(self, body: bytes, requested_url: str, final_url: str) -> Listing:
        page = self.page_number(requested_url)
        if self.page_number(final_url) != page:
            raise ValueError("Pagination redirected to a different page")
        articles = cdon_articles(body)
        marker = re.search(r"Sivu\s+(\d+)\s*/\s*\d+", body.decode("utf-8", "replace"))
        if marker is not None and int(marker.group(1)) != page:
            raise ValueError("Pagination loop: page indicator differs from requested page")
        products = []
        ids = []
        for article in articles:
            slug = str(article.get("slug") or "")
            product_id = slug[-16:]
            if not re.fullmatch(r"[0-9a-f]{16}", product_id):
                raise ValueError(f"Article without a 16-hex id slug: {slug!r}")
            ids.append(product_id)
            if cdon_article_media(article) in ELIGIBLE_FORMATS:
                products.append(
                    Discovery(
                        product_id=product_id,
                        edition_url=urljoin(self.start_url, f"/tuote/{slug}/"),
                    )
                )
        pages = [self.page_url(n) for n in range(1, self.max_pages + 1)]
        return Listing(products=products, pages=pages, signature=tuple(sorted(ids)))
