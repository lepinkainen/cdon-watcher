# MyMovies

MyMovies (<https://www.mymovies.fi>) is the watcher's third store, key
`mymovies`, added 2026-11-12. It sells new and used Blu-rays, 4K UHDs and DVDs.

| Part            | File                                                                   |
| --------------- | ---------------------------------------------------------------------- |
| Requests, crawl | `ingestion/mymovies.py` (`MyMoviesFetcher`, `MyMoviesAdapter`)         |
| Parser          | `ingestion/mymovies_parser.py` (`MyMoviesParser`)                      |
| Wishlist search | `ingestion/search.py` (`MyMoviesSearchAdapter`)                        |
| Fixtures        | `tests/fixtures/mymovies/` (see its README)                            |
| Tests           | `tests/unit/test_mymovies.py`, `tests/integration/test_live_stores.py` |

## Summary

- **Catalogue crawl:** the site search with an empty query lists every
  in-stock Blu-ray and 4K UHD product, 60 per page. On 2026-11-12 that was 2,999
  products on 50 pages, about two and a half minutes at the 2 s delay. A complete
  run expires products it no longer sees: they have sold out.
- **Wishlist searches** run after the crawl, as for the other stores, and
  include out-of-stock products.
- **Everything comes from the search result cards.** No product pages are
  fetched.
- **One card, up to two products:** a card shows a new and a used price with
  separate stock, so it becomes `<id>:new` and `<id>:used`.
- **Requests identify as desktop Chrome**, because the site refuses other
  User-Agents.

## The site

### robots.txt

`User-agent: *` disallows only `/api/`, `/api/smartship/`, `/admin/`,
`/includes/`, `/logs/`, `/maksu/`, `/old-www/`, `/omakokoelma/` and `/vendor/`.
The search page, `/ajax/` and product pages are allowed. There is no `Sitemap:`
line and no crawl delay for `*` (Bingbot gets `Crawl-delay: 5`).

### Search endpoint

`/tuotteet.php?q=…` is an HTML shell with no results. Its script builds a
`FormData` from the filter form `#filtteriForm` and POSTs it to
`/ajax/hae-tuotteet2.php`, which returns JSON:

- `html`: the result cards;
- `pagination`: the paginator HTML (`button.sivu-linkki` with `data-page`, the
  current page marked `btn-primary`);
- `total`: the result count.

Because the form is sent as `FormData`, an unticked checkbox is simply absent
from the request. The filters:

| Filter     | Field         | Values                                                      |
| ---------- | ------------- | ----------------------------------------------------------- |
| Tyyppi     | `tyyppi`      | `1` Elokuva, `2` TV-sarjat & boxit, `4` Keräily, `3` Kaikki |
| Formaatti  | `formaatti[]` | `1` DVD, `2` Blu-ray, `3` 4K UHD                            |
| Kunto      | `saldo[]`     | `0` Uusi, `1` Käytetty                                      |
| Saatavuus  | `saatavuus`   | `1` Vain saatavilla (form default), `0` Näytä kaikki        |
| Hinta      | `kiintea[]`   | `0` Tarjous, `1` Kiinteä                                    |
| Järjestä   | `jarjestys`   | `tuote` (name), `muokattu` (form default), `vuosi`          |
| Hakukenttä | `hakukentta`  | `kaikki`, `elokuva`, `nayttelija`, `ohjaaja`                |

Plus `q` (the query, may be empty) and `page`.

### User-Agent blocking

A POST with a desktop Chrome User-Agent gets HTTP 200, even without cookies, a
`Referer` or other browser headers. Without it the answer is HTTP 403, a
LiteSpeed page ("Access to this resource on the server is denied!"). Headless
Playwright Chromium with its default `HeadlessChrome` User-Agent was also
refused, with a page about the region or user agent not being allowed. The block
is by User-Agent; region blocking is not a concern for the deployment host.

## Requests

`MyMoviesFetcher` turns an archived URL of the search page into the POST, so the
archive records each request as a readable URL and keeps the JSON body:

```text
https://www.mymovies.fi/tuotteet.php?q=<query>&saatavuus=<0|1>[&page=<n>]
```

`parse_url` accepts only those three parameters (`page` 1–1000, omitted for
page 1). The fetcher sends them as multipart form fields together with fixed
ones (`FIXED_FIELDS`):

| Field         | Sent       | Why                                                                       |
| ------------- | ---------- | ------------------------------------------------------------------------- |
| `tyyppi`      | `3`        | All types: box sets come back and are shown as collections, never matched |
| `formaatti[]` | `2`, `3`   | Blu-ray and 4K UHD; DVDs are dropped by the site                          |
| `saldo[]`     | `0`, `1`   | New and used                                                              |
| `kiintea[]`   | `0`, `1`   | Both price kinds (see below)                                              |
| `jarjestys`   | `muokattu` | The form default: last modified first                                     |
| `hakukentta`  | `elokuva`  | Title only; `kaikki` also matches cast and crew                           |

The response is returned under the requested URL, redirects are not followed,
and the User-Agent is a fixed desktop Chrome string (`USER_AGENT`).

| Use             | `q`     | `saatavuus` | Pages                   |
| --------------- | ------- | ----------- | ----------------------- |
| Catalogue crawl | empty   | `1`         | all, from the paginator |
| Wishlist search | a title | `0`         | first page only         |

### Why these filters

**DVDs.** Sending only `formaatti[]=2` and `3` drops DVDs on the server: the
`looper` search went from 14 results to 3. The parse stage drops ineligible
formats anyway.

**Tarjous and Kiinteä are not "on sale" and "full price".** The two values
split the results with no overlap (`looper`: 12 + 2 = 14). Kiinteä items carry a
**Kiinteä hinta** (fixed price) badge; Tarjous items carry no badge, no
crossed-out price and no regular price. So Tarjous means "not fixed price".
Presumably fixed-price items are excluded from store campaigns, but this is not
confirmed. Dropping Kiinteä would hide real offers such as the Looper 4K UHD,
so both are sent.

**Title only.** With `hakukentta=kaikki`, `looper` also returned Casino Jack
and `drive` returned 49 results instead of 19, the extras being Adam Driver
films. Title-only kept every product with the word in its title.

## Catalogue crawl

`MyMoviesAdapter` (scope `in-stock`) starts at the empty query with
`saatavuus=1`, reads the highest `data-page` in the paginator and queues every
page from 1 to it. Each page must:

- be a JSON results response with at least one card;
- have the requested page marked active in the paginator, else it is a
  pagination loop;
- be the in-stock listing (empty `q`, `saatavuus=1`).

Past the last page the site returns the empty placeholder, which the adapter
rejects. `expires_unseen` is true: a complete run marks products it didn't see
inactive, so a sold-out product drops out. A card that is listed because one
condition is in stock still yields both conditions, the other one as out of
stock.

With `saatavuus=0` the listing would be 6,986 products on 117 pages; the crawl
covers in-stock products only, and wishlist searches find out-of-stock wished
products.

The first live run (2026-11-12): 50 pages, 2,999 products, 5,807 imported
offers, no parse errors, 30 flagged as box sets.

## Wishlist searches

`MyMoviesSearchAdapter.search_url` builds `q=<title>&saatavuus=0`.
`result_count` accepts only such URLs and counts the cards. As for the other
stores, `Searcher` falls back to the original title when the title finds
nothing, and `SEARCH_DAILY_CAP` and `SEARCH_MIN_INTERVAL_HOURS` apply.

Results fit on one page in practice (a page holds 60), so only the first page is
read.

Live checks on 2026-11-12 with the request above:

| Query                               | Results | Notes                                                                                        |
| ----------------------------------- | ------- | -------------------------------------------------------------------------------------------- |
| `Taxi Driver`                       | 4       | All `Taxi Driver / Taksikuski` products                                                      |
| `Taksikuski`                        | 4       | Same 4: Finnish titles are searchable                                                        |
| `The Dead Don't Die` (straight `'`) | 1       | Finds `The Dead Don’t Die`: apostrophes are normalized                                       |
| `The Dead Don’t Die` (curly `’`)    | 1       | Same product                                                                                 |
| `Mission: Impossible`               | 14      | Also finds `Mission Impossible - …` and `M:I -2 / Vaarallinen tehtävä 2`                     |
| `Mission Impossible`                | 14      | Same 14: punctuation is ignored                                                              |
| `Fast & Furious`                    | 16      | `&` works; also finds `The Fast and the Furious 6`                                           |
| `Amélie` / `Amelie`                 | 1       | Both find only `La signora senza camelie`: accents are folded, Amélie isn't stocked on BD/4K |
| `65`                                | 2       | Both `65` products, no stray numeric hits                                                    |
| `Kummisetä`                         | 8       | `ä` works; Godfather products plus `Gotti - Viimeinen kummisetä`                             |
| `The Godfather`                     | 10      | Mostly sequels, trilogies and collections; title and year matching must pick Part I          |
| `zzqxnotamovie`                     | 0       | The empty placeholder                                                                        |

The site normalizes punctuation, apostrophes and accents and matches part of
the title (`Amelie` hits `camelie`). Titles are stored under both the original
and the Finnish name, so the TMDB title works. Results include sequels,
collections and longer titles; matching sorts them out.

An empty search is HTTP 200 with `total` `0`, `pagination` `""` and `html`
`<div class="col-12 text-muted">Ei tuloksia valituilla ehdoilla.</div>`; the
parser treats it as a valid, empty answer. A blocked request is HTTP 403 with an
HTML page, never JSON, so it is recorded as a failed search.

## Parsing

`MyMoviesParser` (version `mymovies-1`) reads `div.col > div.card` from the
`html` field, for crawl pages (`parse`, where an empty page is an error) and
searches (`parse_search`, where no results is fine). A response that is not
JSON, has an `error`, or lacks `html` or `total` is a parse error.

| Field                | Source in the card                                                                    |
| -------------------- | ------------------------------------------------------------------------------------- |
| Product id           | The link `tuotetiedot.php?id=N`                                                       |
| Title                | `.tuote-nimi`, the product name (`Looper (Blu-ray)`); `clean_title` strips the format |
| Format               | The first badge: `DVD`, `Blu-ray` or `4K UHD`; a UHD + Blu-ray combo is 4K            |
| Edition note         | `Kiinteä hinta` when a later badge says so                                            |
| Price, per condition | The `Uusi: 15,00 €` and `Käytetty: 8,00 €` lines                                      |
| Stock, per condition | The buy button's `data-uusi` and `data-kaytetty` (`1` = in stock)                     |
| Raw availability     | The hex colour of the dot before the price line                                       |
| Year                 | `<small>(2012)</small>`; some cards have none                                         |
| Image                | `img.card-img-top`                                                                    |
| Collection           | `is_box_set(title)`                                                                   |
| Store page           | `https://www.mymovies.fi/tuotetiedot.php?id=N`                                        |

Not read: the last-modified date (`<small>10.09.26</small>`). There is no
regular price or stock quantity.

### Two products per card

Each condition that shows a price becomes its own product, `<id>:new` or
`<id>:used`, with the same store page. A line like `Uusi: -` means the
condition is not offered and produces nothing.

The watcher holds one condition per product (`StoreProduct` is unique on store
and product id, and the importer keeps the first product with a given id in a
run), so a single id per card would silently lose one offer. With one id per
condition the importer, schema, price history, the condition filter and
`/api/v2/offers` need no changes. Consequences:

- Each condition has its own price history and stock.
- Ignore and manual match act on one condition: ignoring the used copy leaves
  the new one visible.
- Matching runs per product, but the second condition normally reuses the first
  one's match (same cleaned title and year) instead of searching TMDB again.

### Stock

Stock is shown twice on a card and the two agreed on all 63 cards checked:

- The buy button's flags; a card with nothing in stock has no button, which the
  parser reads as out of stock in both conditions.
- The dot colour: red `#dc3545` is out of stock, green `#28a745` and yellow
  `#ffc107` are in stock.

The product pages agree. Neither the card nor the product page explains green
versus yellow ("Saatavuus koskee verkkokaupan varastoa"); both count as in
stock. A price is shown even for a condition that is out of stock.

## Matching

Matching uses title and year only, never EAN. Wishlist entries carry a movie
name, year and TMDB id and never an EAN, and the store's EANs are not accurate
enough to rely on. Finnish release titles may differ from TMDB's, so the year
matters.

## Not used

### Sitemap

`/sitemap.xml` (also `/sitemap.php`) is a single 4.5 MB `urlset` of 32,907
URLs: 32,906 `tuote.php?id=N` (ids 52–36823) plus the front page, each with only
`lastmod` and `priority`. The URLs carry no title, and a scan would cost one
request per product (about 27 h at one request per 3 s). The empty search lists
the in-stock catalogue in 50 requests instead.

### Product pages

`tuote.php?id=N` redirects (301) to `tuotetiedot.php?id=N`. The page has no
JSON-LD or `product:` meta tags, but its HTML gives:

- `og:title`: `<product name> / <movie> (<year>) – <format>`, or
  `<movie> (<year>) – <format>` when the names match, followed by
  `| DVD Blu-ray 4K UHD Elokuvat ja TV-boksit | MyMovies`;
- new and used prices with stock in the label (`OSTA KÄYTETTYNÄ 4,00 €`,
  `EI SAATAVILLA UUTENA 14,00 €`) and "Käytettynä: Saatavilla / Uutena: Ei
  saatavilla";
- `EAN:`, year, director and cast.

Checked on Magnolia (1394) and the three Looper editions:

| id    | Format  | Product name            | EAN           | Used                  | New                   |
| ----- | ------- | ----------------------- | ------------- | --------------------- | --------------------- |
| 4836  | DVD     | Looper (2012)           | 6416548568515 | 4,00 € available      | 14,00 € not available |
| 14092 | Blu-ray | Looper (Blu-ray)        | 6416548568539 | 8,00 € available      | 15,00 € available     |
| 36119 | 4K UHD  | Looper (4K UHD+Blu-ray) | 5053083227623 | 15,00 € not available | 30,00 € available     |

The search cards carry everything the watcher uses, so product pages would
only add EAN, director and cast. They remain a fallback if the card markup
changes.
