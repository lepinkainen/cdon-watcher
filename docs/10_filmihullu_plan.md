# Filmihullu-leffakauppa: integration investigation

Status: investigated 2026-11-11, not started. Nothing here is built.

Store: Filmihullu-leffakauppa (`https://www.filmihulluleffakauppa.com/fi/`), a
specialist movie shop in Kamppi, Helsinki, that also sells online. It claims
over 20 000 DVD, Blu-ray and 4K UHD titles and carries many boutique and import
labels (Vinegar Syndrome, Arrow, UK releases) that Äx and CDON lack. That
range is the reason to add it.

## Summary

| Question                   | Answer                                                                                                                                                                       |
| -------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Platform                   | PrestaShop 8/9 (Hummingbird-style theme `product-miniature__*`, Creative Elements page builder, `wkelasticsearch` search module)                                             |
| Plain HTTP                 | **No.** Every path, including `robots.txt`-listed sitemaps, returns a Cloudflare managed challenge (`HTTP 403`, `cf-mitigated: challenge`). `robots.txt` itself is reachable |
| Browser                    | `BrowserFetcher` gets through on the first page load, with two fixes (see [Fetcher](#fetcher-changes))                                                                       |
| Listing data               | Server-rendered HTML tiles carry title, price, stock text and product id. No `__NEXT_DATA__`-style JSON state                                                                |
| Offers category            | Exists only as `/fi/?controller=prices-drop`, which **`robots.txt` disallows**                                                                                               |
| Pagination                 | PrestaShop `?page=N`, which **`robots.txt` disallows**                                                                                                                       |
| Search                     | `/fi/?controller=search&s=`, which **`robots.txt` disallows**                                                                                                                |
| What robots.txt does allow | Query-free category pages (page 1 only), query-free product pages, sitemaps                                                                                                  |
| Recommended integration    | Sitemap title index, then product pages only for wished movies. Browsing offers is not possible within the rules                                                             |

The site is technically easy to parse, but the operator's rules leave very
little room. Read [Caveats](#caveats) before writing any code; the first
decision is not technical.

## What was observed

### Cloudflare

- `curl` to `/fi/`, `/1_sitemap_index.xml` and `/sitemap.xml`: `403` with
  `cf-mitigated: challenge`. Unlike CDON there is no "maybe it works with the
  right headers" path; the challenge is site-wide.
- Through the project's `BrowserFetcher`, `/fi/` rendered fully (452 kB, 30
  product tiles). `/1_sitemap_index.xml` in the same browser context came back
  as the challenge page, not the sitemap; see the fetcher notes below.
- The challenge page is localized: with `locale="fi-FI"` its title is
  **`Pieni hetki...`**, not `Just a moment...`. `BrowserFetcher` only looks for
  `just a moment`, so it returned the challenge body with status 200. Any
  integration must guard on this; it would also bite CDON if Cloudflare starts
  localizing there.
- Each fetch took about 22 s because `BrowserFetcher` waits up to 20 s for
  `script#__NEXT_DATA__`, which this site never has.

Further browser probing (category pages, product page, sitemap retry) was not
done. The coding agent's permission policy classified repeated headless
fetches through the challenge as bot-check circumvention and stopped it. That
is itself a signal worth weighing; see [Caveats](#caveats). Everything below
about product pages and sitemaps is therefore **expected PrestaShop behaviour,
not verified on this site**, and is marked so.

### robots.txt (fetched 2026-11-11, operator comment dated 2026-10-25)

Two layers: a Cloudflare-managed block (`User-agent: *`, `Allow: /`,
`Content-Signal: search=yes,ai-train=no,use=reference`, AI training bots
disallowed) followed by the operator's own rules. The ones that matter:

```
User-agent: *
Disallow: /en/
Allow: /fi/content/
Disallow: /*?
Disallow: /*&
Disallow: /*controller=search
...
Sitemap: https://www.filmihulluleffakauppa.com/1_sitemap_index.xml
Sitemap: https://www.filmihulluleffakauppa.com/blog_sitemap.xml
Sitemap: http://www.filmihulluleffakauppa.com/sitemap.xml
```

The operator's comment on `/*?` reads, translated: _"Block parameters (the most
important CPU saver). Covers ALL parameter URLs: facet searches, filters,
?search_query=, ?order=, ?tag=, ?id_currency=, ?back=, ?n=, pagination etc."_
Another comment mentions a crawler doing ~146 000 brand-filter requests a day.
CPU load from crawlers is a real, stated problem for this shop.

`urllib.robotparser` agrees with the reading above (checked offline):

| URL                                              | Allowed |
| ------------------------------------------------ | ------- |
| `/fi/blu-ray`                                    | yes     |
| `/fi/blu-ray?page=2`                             | no      |
| `/fi/?controller=prices-drop`                    | no      |
| `/fi/?controller=search&s=alien`                 | no      |
| `/fi/module/wkelasticsearch/wkelasticajaxsearch` | yes\*   |
| `/1_sitemap_index.xml`                           | yes     |

\* Allowed only because the rule targets `/modules/` (the filesystem path) and
`controller=search`, not the search module's front controller. Using it would
follow the letter of the file while defeating its stated intent (no search
load from bots), and it needs a per-session `data-token`. **Do not use it**
without the shop's permission.

### URL structure

- Language prefix `/fi/`; `/en/` is a dead duplicate and disallowed.
- Format categories: `/fi/blu-ray`, `/fi/4k-uhd`, `/fi/dvd`, plus genre ×
  format pages (`/fi/kauhu-4k-uhd`, `/fi/import-blu-ray`, `/fi/klassikot-blu-ray`,
  …), `/fi/uutuudet` (new), `/fi/tulossa-blu-ray` (coming), `/fi/steelbookit`,
  `/fi/kokoelmat-blu-ray` (collections), `/fi/tv-sarjat-blu-ray`.
- Product URLs: `/fi/<default-category>/<slug>`, e.g.
  `/fi/4k-uhd/gone-with-the-wind-1939-steelbook-4k-uhd-2-blu-ray`. No numeric id
  in the URL. The slug carries title, year and format, which makes a slug index
  useful for matching.
- Images: `/<image-id>-<size>/<slug>.jpg|webp`, sizes `default_sm`,
  `default_md`, `default_lg`, `home_default`.

### Listing tile (homepage, verified)

The homepage and category pages use the same PrestaShop miniature. One tile:

```html
<article
  class="product-miniature js-product-miniature"
  data-id-product="24176"
  data-id-product-attribute="0"
>
  <a
    class="product-miniature__image-link"
    href="…/fi/4k-uhd/gone-with-the-wind-1939-steelbook-4k-uhd-2-blu-ray"
  >
    <img
      class="product-miniature__image"
      src="…/45201-default_md/….jpg"
      data-full-size-image-url="…/45201-home_default/….jpg"
    />
  </a>
  <a class="product-miniature__title" href="…"
    >Gone with the Wind (1939) Steelbook (2 4K UHD + Blu-ray)</a
  >
  <div class="fh-miniature__desc">
    original title, Ohjaus, Pääosissa, Tekstitys …
  </div>
  <div class="fh-miniature__stock csd-stock-wrapper">
    <p class="csd-stock csd-stock--ok">✓ Varastossa yli 5kpl</p>
  </div>
  <div class="product-miniature__prices">
    <div class="product-miniature__price">49,95&nbsp;€</div>
  </div>
  <ul class="product-flags js-product-flags">
    <li class="badge new">Uusi</li>
  </ul>
</article>
```

Field mapping to `ParsedProduct`:

| Field                 | Source                                                                                                                                                  |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `product_id`          | `article[data-id-product]` (PrestaShop `id_product`, integer)                                                                                           |
| `raw_title`           | `.product-miniature__title` text                                                                                                                        |
| `edition_url`         | `.product-miniature__title[href]`                                                                                                                       |
| `format`              | `format_from_text(title)`; the URL's first segment (`blu-ray`, `4k-uhd`, `dvd`) as a fallback                                                           |
| `release_year`        | `(YYYY)` in the title, almost always present                                                                                                            |
| `price_cents`         | `.product-miniature__price` through `parse_price_cents` (handles `49,95\xa0€`)                                                                          |
| `regular_price_cents` | **Unverified.** No discounted tile on the homepage. PrestaShop renders `.product-miniature__regular-price` (or `.regular-price`) plus a `discount` flag |
| `availability`        | `.csd-stock` modifier class, see below                                                                                                                  |
| `stock_quantity`      | `Varastossa N kpl.` → N; `yli 5kpl` → None                                                                                                              |
| `condition`           | Always `new`. No used stock seen                                                                                                                        |
| `image_url`           | `img[data-full-size-image-url]`                                                                                                                         |
| `is_collection`       | `box_set_detector`, plus the title's disc count (`(6 Blu-ray)`), `Trilogy`, `Season N`                                                                  |

Stock wording seen across 30 tiles (`csd-stock` comes from a third-party
"custom stock display" module, so wording is configurable by the shop):

| Class            | Text                                          | Availability     |
| ---------------- | --------------------------------------------- | ---------------- |
| `csd-stock--ok`  | `✓ Varastossa yli 5kpl`                       | `IN_STOCK`       |
| `csd-stock--low` | `Varastossa 3 kpl.`                           | `IN_STOCK`, qty  |
| `csd-stock--out` | `✗ Toimitusaika 1-2 vko`                      | `SUPPLIER_ORDER` |
| no stock element | `Julkaisupäivä 16.11.2026` in the description | `PREORDER`       |

Parse the modifier class first and the text second; the class survives copy
edits. Stock may include the physical shop's shelf. "In stock" online can
still sell out in the shop the same day.

Titles carry edition and region noise the cleaner must handle:
`Steelbook`, `Limited Edition` (and the typo `Limtied Edition`), `UK`,
`(4K UHD + 2 Blu-ray)`, `(Blu-ray + DVD)`, `(2026– )` for TV. The existing
`clean_title` strips bracketed groups containing a format word, but `UK` and
`Limtied Edition` outside brackets survive. Add fixture-driven tests.

The page also embeds a schema.org `ItemList` (names and URLs only, no prices)
and the PrestaShop `prestashop = {…}` JS config. Neither carries prices, so
the HTML tiles are the source.

### Product page (expected, not verified)

A stock PrestaShop 8 product page has:

- `<script type="application/ld+json">` `Product` with `offers.price`,
  `offers.priceCurrency`, `offers.availability` (schema.org URL), `sku`/`gtin13`
  (EAN, useful for exact matching later), `image`, `brand`.
- `#product-details[data-product]`: JSON with `id_product`, `price_amount`,
  `regular_price_amount`, `quantity`, `availability`, `reference`, `ean13`.
- The same `csd-stock` block.

Prefer `data-product` JSON, then JSON-LD, then the visible markup. Capture a
fixture and confirm before writing the parser.

### Sitemap (expected, not verified)

PrestaShop's `gsitemap` module writes `1_sitemap_index.xml` pointing to files
such as `1_fi_0_sitemap.xml`, each with `<url><loc>…</loc><lastmod>…</lastmod>
<image:image>…</image:image></url>`. No prices. `/en/` URLs may appear and
must be dropped. Expect 20 000+ product URLs over a handful of files.

## Caveats

1. **The operator has said no to the useful parts.** Offers, pagination and
   search all sit behind query strings that `robots.txt` disallows, with an
   explicit comment that bot load on those URLs is a CPU problem. The tracker's
   core use, "offers under a price cap", needs `prices-drop` plus pagination.
   That cannot be done within the rules.
2. **A site-wide Cloudflare managed challenge.** CDON's challenge was accepted
   because the pages themselves were allowed. Here the challenge sits on top of
   rules that already exclude most of what we would fetch. During this
   investigation the agent's own permission policy blocked further headless
   fetches as bot-check circumvention. Make this call deliberately, not as an
   implementation detail.
3. **It is a small independent shop.** The cheapest robust option is to ask.
   PrestaShop shops often already export a product feed (Google Merchant,
   price-comparison sites) with price, availability and EAN. A feed URL from
   the shop would replace everything below with one plain-HTTP request a day
   and needs no browser. **Recommendation: email the shop before building.**
4. **No used condition, no marketplace.** Simpler than CDON: one seller, new
   discs only.
5. **Product URLs depend on the default category.** A product moving from
   `/fi/tulossa-blu-ray/` (coming soon) to `/fi/blu-ray/` on release changes its
   URL. Key products on `id_product`, never on the URL.
6. **Prices include VAT** (`display_prices_tax_incl: true`), EUR, matching the
   other stores.

## Implementation options

Ordered by how well they fit the rules. Option A is the recommended default
if the shop is not asked or does not reply; option F replaces everything if
the shop provides a feed.

### A. Wishlist via sitemap index plus product pages (recommended)

Fits phase 2's wishlist searches without a search endpoint.

1. **Index stage** (`crawl-raw --store fh`, scope `sitemap`): fetch the sitemap
   index and its children, at most daily, and archive them like listing pages.
   That is a few requests a day.
2. **Parse**: build a slug index `{url, slug, lastmod}` from product `<loc>`s
   under `/fi/`. The slug is `title-year-edition-format`, for example
   `the-death-of-robin-hood-2026-blu-ray`. Do not import these as products: no
   price, no stock.
3. **Search stage** (`FhSearchAdapter`): instead of a search URL, look up each
   wished movie in the local slug index (slugified title and original title,
   plus year when known; keep format words for filtering) and fetch only the
   matching product pages, at most a few per wish, under `SEARCH_DAILY_CAP`.
   Each product page is one allowed, query-free request.
4. **Parse product pages** into `ParsedProduct` with `search_tmdb_id` set, as
   the CDON and Äx search parsers do, so `score_target` and `/api/v2/offers`
   work unchanged.

Fit with the current code:

- `Searcher` assumes one fetch per query returning a result count. Option A
  needs "resolve query locally → 0..n product fetches". Either give
  `SearchAdapter` an optional `resolve(query) -> list[str]` that `Searcher`
  calls before fetching, or add a small `FhSearcher` that writes the same
  `wish-search` archive (manifest fields `search_tmdb_id`, `search_query`). A
  query with no slug hit is recorded as a successful empty search, not a
  failure.
- The slug index must be readable from the search stage. Store it as the
  latest sitemap run's `parsed.json`, or as a small `fh_slugs` table through a
  `MIGRATIONS` entry. The archive is simpler and keeps the stages offline.
- `expires_unseen = False`; freshness hides stale rows as for CDON.

### B. Query-free category first pages (supplementary)

`/fi/blu-ray`, `/fi/4k-uhd`, `/fi/uutuudet` and the `tulossa-*` pages, page 1
only. The homepage carried 30 tiles; category page size is unverified. That is
a "new arrivals" glimpse of about 100 products a day, without discounts. Useful
as a cheap discovery source with the same tile parser, not as an offers
feed. If built, `FhAdapter.page_number` must reject any query string, so a
paginator link can never be followed.

### C. Offers and pagination (`prices-drop`, `?page=N`)

Disallowed. Listed only to rule it out. Revisit only with written permission.

### D. Search module AJAX (`/fi/module/wkelasticsearch/wkelasticajaxsearch`)

Not covered by `robots.txt` by accident; see the note above. Needs a page
token, and it is exactly the load the operator wants to avoid. Do not build
it without permission.

### E. Full crawl of product pages from the sitemap

20 000+ browser renders a day. No.

### F. Shop-provided feed

If the shop provides a feed: plain `HttpFetcher`, one request, a feed parser
(XML or CSV), `expires_unseen = True` when the feed is the full catalogue. No
browser, no Cloudflare. Search becomes a local lookup over the imported
products.

## Fetcher changes

Needed for any option that uses the browser:

1. **Localized challenge title.** Match `just a moment|pieni hetki` (or check
   for the `#challenge-error-text` / `cf-chl` markers instead of the title).
   Without this the archive stores the challenge page as a successful 200.
   Worth fixing for CDON as well.
2. **Per-store readiness selector.** Replace the hard-coded
   `script#__NEXT_DATA__` wait with a selector passed per adapter
   (`article.js-product-miniature` for listings, `#product-details` or
   `script[type="application/ld+json"]` for product pages). This removes the
   20 s timeout on every page.
3. **XML bodies.** For sitemaps, `page.content()` returns Chromium's XML
   viewer DOM, not the XML. After the challenge clears, take the body from the
   navigation response (`response.body()`) or a `context.request.get()` in the
   same context, which reuses the clearance cookie.
4. **Cookie banner.** None appeared on the rendered homepage; leave the Didomi
   JS as a harmless no-op.

## Wiring checklist

Store key `fh` (short, like `ax`).

- `ingestion/stores.py`: `FhAdapter` (option B) or a sitemap adapter (option A), with
  strict `page_number` / URL validation as in `AxAdapter`.
- `ingestion/fh_parser.py`: tile parser (`parse`), product-page parser
  (`parse_search`), `version`, `expires_unseen = False`.
- `ingestion/search.py`: `FhSearchAdapter` or `FhSearcher`;
  `make_search_adapter`.
- `refresh.py`: `STORES`, parser map, `make_adapter`, and the browser choice
  (CDON currently gets `BrowserFetcher` by store name; make that an adapter
  attribute such as `needs_browser = True`).
- `config.py` / `.env.example`: `STORES` default stays `ax,cdon` until the
  shop question is settled.
- Web: `store=fh` filter value and display name "Filmihullu" in
  `web/filters.py` and templates; the offers API's `store` field (check
  moviecatalog `SPEC.md` for allowed values first, since the contract changes
  there).
- Tests: gzip fixtures under `tests/fixtures/fh/` (homepage or category page,
  one discounted tile, one product page per availability state, one sitemap
  child) with a README; unit tests for stock classes, title cleaning (`UK`,
  `Limtied`), id extraction and challenge detection; a live shape test in
  `tests/integration/test_live_stores.py`.
- `ai-docs/crawler-investigation.md`: a "Filmihullu" section with the expected
  shape and the traps above.

## Open questions

- Does the shop already publish a product feed, and may we use it? (Ask
  first.)
- Category page size and whether query-free category pages are server-rendered
  the same way as the homepage tiles.
- Discounted tile markup (`regular_price_cents`).
- Product page `data-product` / JSON-LD presence and the EAN field.
- Sitemap file names, size and whether `lastmod` tracks price or stock changes
  (probably not; PrestaShop sets it on product edit).
