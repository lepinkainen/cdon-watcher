"""Store-specific discovery. No normalized products or database writes."""

import re
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup

from .archive import Discovery


@dataclass
class Listing:
    products: list[Discovery]
    pages: list[str]
    signature: tuple[str, ...]


class StoreAdapter(Protocol):
    key: str
    scope: str
    start_url: str

    def discover(self, body: bytes, requested_url: str, final_url: str) -> Listing: ...


class AxAdapter:
    key = "ax"
    scope = "movie-offers"
    start_url = "https://www.levykauppax.fi/leffat/offer/"

    def page_number(self, url: str) -> int:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "www.levykauppax.fi"
            or parsed.path != "/leffat/offer/"
            or parsed.fragment
        ):
            raise ValueError(f"URL outside offer scope: {url}")
        query = parse_qs(parsed.query, keep_blank_values=True)
        if query and (set(query) != {"p2"} or len(query["p2"]) != 1):
            raise ValueError(f"Unexpected pagination query: {url}")
        page = int(query.get("p2", ["1"])[0])
        if not 1 <= page <= 1000:
            raise ValueError(f"Invalid or excessive page number: {page}")
        return page

    def discover(self, body: bytes, requested_url: str, final_url: str) -> Listing:
        page = self.page_number(requested_url)
        if self.page_number(final_url) != page:
            raise ValueError("Pagination redirected to a different page")
        soup = BeautifulSoup(body, "html.parser")
        heading = soup.select_one("h1")
        if heading is None or heading.get_text(" ", strip=True) != "Elokuvat - Tarjoukset":
            raise ValueError("Missing movie offer heading; possible error page")
        active = soup.select_one(".pagination .active")
        if active is not None and active.get_text(strip=True) != str(page):
            raise ValueError("Pagination loop: active page differs from requested page")
        rows = soup.select("ul.list-products > li.hproduct")
        if not rows:
            raise ValueError("Empty or unrecognized offer listing")
        products = []
        ids = []
        for row in rows:
            product_id = str(row.get("id", "")).removeprefix("p-")
            link = row.select_one("a.fn[href]")
            media = row.select_one("span.type")
            if not product_id.isdecimal() or link is None or media is None:
                raise ValueError("Offer row lacks an edition ID, title link, or format")
            ids.append(product_id)
            edition_url = urljoin(self.start_url, str(link["href"]))
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
        linked_pages = [page]
        for link in soup.select(".pagination a[href]"):
            linked_pages.append(self.page_number(urljoin(self.start_url, str(link["href"]))))
        # Fetch intermediate pages even if the paginator abbreviates them with an ellipsis.
        pages = [
            self.start_url if n == 1 else f"{self.start_url}?p2={n}"
            for n in range(1, max(linked_pages) + 1)
        ]
        return Listing(products=products, pages=pages, signature=tuple(sorted(ids)))
