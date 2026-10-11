# Physical movie store database plan

Status: implementation started, 2026-09-21. Open questions resolved the same
day; this is the v1 spec. Step 1 is implemented. Steps 2–7 remain pending,
and the existing application still uses the proof-of-concept pipeline.

The standalone command `uv run python -m cdon_watcher crawl-raw --store ax`
saves offer listing responses under `data/raw/ax/<run>/`, without database
imports or TMDB calls. Use `--raw-dir` to select another archive directory.
Requests default to a two-second delay and three attempts per page; `--delay`
and `--attempts` override these values. Incomplete crawls retain their responses
and return exit code 1. A concurrent crawl for the same store returns exit code 2.
The manifest records discovery counts, edition links, failures, and response
provenance. Saved fixtures and offline tests cover the first and last offer pages.

## Operating context

- Single-user application. Runs locally or on a VPS behind Tailscale.
- No logins, sessions, or access control. The UI is read-only apart from
  watchlist, ignore, and manual-match actions, and those are trusted.
- The existing CDON-only application is a proof of concept. This multi-store
  version is the real product. The current database holds nothing worth
  keeping and will be deleted; no schema or data migration is required.
- This is a rewrite, not an incremental extension of the proof of concept.
  Its schema, API, UI, and workflows impose no compatibility requirements.
  Treat the old code as reference material and reuse only working parts that
  fit the new design, such as store selectors, parsing helpers, and TMDB access.
- Reset the old database once when switching to the new application. Normal
  startup must preserve the new database, price history, and user preferences.
- Deployment target is a single Docker container (web app plus scheduled
  refresh) on a VPS or local machine. fly.io is dropped as too expensive:
  remove `fly.toml`, fly-specific env handling, and fly references in docs.
  The image must include Playwright and Chromium for the CDON adapter.
- No notifications in v1. Remove the Discord webhook code path.
- Be polite to stores: minimise request count, keep a delay between requests,
  and fetch only pages the pipeline needs.

## Agreed scope

- Keep CDON, scoped to the first N listing pages of `https://cdon.fi/elokuvat/`
  per format filter (Blu-ray, 4K), N configurable with default 10, as today.
  CDON has no offer category, so this page limit is CDON's normal scope and
  does not make a CDON run incomplete.
- Add Levykauppa Äx, limited to <https://www.levykauppax.fi/leffat/offer/>
  and products discovered there.
- Include Blu-ray and 4K UHD, both new and used. Exclude DVD-only products.
  Keep steelbooks, combined 4K/Blu-ray releases, and multi-disc editions.
- Front-page price limits are hardcoded constants in v1: Blu-ray at €10 or
  less and 4K UHD at €20 or less, excluding shipping. Query parameters can
  override them for one view; there is no env or settings configuration.
  Apply the same limits to new and used products.
  Combined 4K/Blu-ray editions use the 4K limit. Collections use the limit for
  their format against the whole product price, with no per-movie calculation.
- Record a price observation for every product on every successfully imported
  crawl, including unchanged prices. Keep this history for future analysis;
  front-page filtering uses only the current price.
- Store the store's crossed-out regular price when it is displayed (Äx uses
  `<del>`), as optional metadata for future analysis. It does not affect
  front-page eligibility.
- Sale percentages and other historical price comparisons are out of scope for
  the first version. No discount calculations, filters, badges, or sorting are
  required. Keep timestamped price history so they can be added later.
- Use TMDB for movie identity and retain an optional IMDb ID when TMDB provides
  it. No separate IMDb or OMDb API integration is required.
- Collections (multi-movie boxes and TV-show season or series packages) are
  parsed and displayed as-is under the original store title. No TMDB matching
  of any kind for them in v1; the proof of concept showed this to be complex
  and flaky. TMDB matching in v1 covers single movies only.
- Crawl, parse, and match eligible products regardless of stock status or
  current price. Only confirmed in-stock products appear in the shopping UI.
  Preorders, out-of-stock items, supplier orders, and unknown availability stay
  in the database but remain hidden, including from user-facing match queues.
- The main flow is browsing qualifying offers and following a link to the exact
  store edition to buy manually.

## Findings from the existing application and live site

The existing application uses Python, SQLModel, SQLite, FastAPI, and server-side
templates. Retain that stack and the existing package name for this work.

`ProductParser` currently fetches pages as part of parsing. `PageCache` replaces
and expires responses, so it is not a replayable raw archive. `Movie` represents
a store product but has a globally unique `product_id` and no store key.
`PriceHistory` has no regular price, currency, or link to the crawl that
produced it. Replace the existing deals query, which compares consecutive price
observations, with current-price filters by format. The existing stock expiration
uses time since the last update rather than completed crawl membership.
Automatic TMDB lookup selects the
first result, while manual review is tied to watchlist and ignore actions.
These responsibilities need separating. Because the database is disposable,
none of this constrains the new schema.

Live inspection confirmed that ordinary HTTP requests return Äx product listing
HTML. Playwright also confirmed pagination and product navigation. The category
reported 1,339 products over 14 pages during inspection; these counts are not
constants. Pagination used `?p2=2`. Listing rows exposed numeric product IDs,
titles, format, stock text, current prices, and `<del>` regular prices. Product
pages added EAN, subtitles, language, and edition information.

An Äx title page contains several product editions. Listing URLs such as
`/movie/mission_impossible_the_final_reckoning/#1120921` identify the particular
edition through their fragment. Download the document once per crawl, but keep
each product ID and edition link. Only import editions discovered in the offer
category; other editions and recommendations on detail pages do not expand scope.

## Pipeline

### Scheduled operation

A timer or cron job runs a refresh command, daily by default and also available
manually. For each store, it performs these stages in order:

1. Fetch raw store responses and persist them to disk.
2. Parse those saved responses offline and import products and observations
   into SQLite.
3. Match new or unresolved individual movies through TMDB. Skip collections.

The UI uses the database as its product and price data source. Opening a page
does not fetch store pages or trigger the ingestion pipeline. It remains usable
during refreshes and reads committed data. Failed fetches or parses must not
wipe existing records; the normal freshness rules still apply.

Expose crawl, parse/import, and match as independently runnable commands as
well as the combined refresh command. A parser fix can therefore reprocess a
saved run without downloading it again, and matching can retry after a TMDB
failure. Allow only one refresh per store at a time, including manual runs.
Use one scheduling mechanism per deployment to avoid duplicate scheduled jobs.

### 1. Crawl raw data

Introduce a small store adapter interface with CDON and Äx implementations.
Adapters own URL discovery, pagination, and retrieval. The crawler may inspect
markup to discover links and eligible formats; it does not write normalized
products, apply shopping price limits, or call TMDB.

Which pages each adapter fetches in v1:

| Store | Listing pages                                  | Detail pages                                 |
| ----- | ---------------------------------------------- | -------------------------------------------- |
| Äx    | All offer-category pages (`?p2=N`), plain HTTP | None. Listing rows carry everything v1 needs |
| CDON  | First N pages per format, Playwright           | Product page per discovered URL, plain HTTP  |

Äx detail pages (EAN, language, subtitles) are not fetched in v1. CDON product
pages are required because the listing exposes only URLs.

Save every response with a run ID, store, scope, requested and final URL, fetch
time, HTTP status, content hash, and body reference. Use a run manifest and
compressed response files under `data/raw/<store>/<run>/`. Runs are numbered
incrementally per store and never overwrite each other. Retention is forever in
v1; cleanup is v2. For the browser-driven CDON listing, the stored body is the
rendered HTML after JavaScript execution; there is no separate raw response. A
parser-side cleanup step for that HTML is out of scope for v1.

Fetch with bounded retries and a delay between requests. An Äx run is incomplete
when an offer page is missing, pagination loops, or a page fails after retries.
A CDON run is incomplete when a listing page or a required product page fails
after retries; reaching the page limit is normal. Incomplete runs are still
saved and still imported, because fetching and parsing are separate stages and
partial data is better than none. Incompleteness only affects expiry (below).
A transient error page must not become an empty catalog. Record counts and
failure reasons for diagnosis.

### 2. Parse and import offline

Each store parser consumes saved responses and returns a shared product record.
It performs no HTTP requests or TMDB calls. Parsing and database import can run
again without crawling; by default the parse command processes the latest run
for a store, and accepts an explicit run number. Associate every normalized
observation with its source snapshot and parser version.

Normalize format, condition, and availability while preserving their raw text.
Retain the original title and a separate cleaned title for matching. Extract
edition identifiers, EAN, year, and descriptive metadata where present in the
fetched pages. A
multi-disc single movie must not be classified as a collection solely because it
contains more than one disc.

Use integer minor currency units for prices and an explicit currency. Every
observation carries the current price; the regular price is optional and only
recorded when the store displays it. Reject invalid prices; never derive a
regular price from history. If listing and detail data conflict, record the
conflict and withhold shopping visibility until the relevant edition's price and
stock are unambiguous.

Import transactionally and idempotently. Replaying the same snapshot must not
append duplicate history or change its observed timestamp. Reprocessing an old
run must not replace newer current state. Parsing errors must not erase good
records or count as evidence that products disappeared.

Identify observations by product and crawl run, not only by response content
hash. Identical content fetched on a later run is still a new observation;
reparsing the same run updates its parsed result without duplicating history.

### 3. Match movie identity

Run TMDB enrichment as a separate retryable stage after import. Reuse proven
TMDB access code where useful, but implement matching and manual review without
a dependency on a watchlist action. A TMDB outage must not interrupt crawling
or parsing.

Use cleaned and alternate titles, production year, and other available evidence
to evaluate candidates. Do not confuse a disc release year with a movie's
production year. Accept an automatic match only with sufficient evidence and
separation from competing candidates. Otherwise store candidates and mark the
product ambiguous or unmatched. The confidence threshold is chosen by judgement
in v1 and tuned by hand; a labelled golden set and calibration tests are v2.
Popularity alone is not identity evidence.

Keep manual matches across future imports. Cache and reuse established matches
when edition identifiers or sufficient movie evidence agree. Collections have
an explicit `not_applicable` match status and never enter the matching queue.
Stock changes do not discard matches. Hidden products still receive automatic
matching, but uncertain hidden products do not require user attention.

### 4. Filter current prices and show the database

The front page queries the database without crawling or calculating historical
price changes. A qualifying product has a current, successfully parsed
observation, confirmed stock, an eligible format, and a current EUR price at or
below its format's limit:

| Format                                         | Default maximum item price |
| ---------------------------------------------- | -------------------------- |
| Blu-ray                                        | €10.00                     |
| 4K UHD, including combined 4K/Blu-ray editions | €20.00                     |

Compare integer cents with inclusive limits of 1000 and 2000. A product can
qualify on its first observation; no previous or regular price is required.
Changing historical observations does not change current-price eligibility.
Price history remains available in the database and the per-product history view.

For Äx, require active membership in the offer category. Only a complete and
parsed Äx run may mark previously seen Äx offers inactive. Disappearance means
the offer ended or left scope, not that the product sold out. Incomplete runs
import their observations but do not expire unseen products, and one store's run
never expires another's. CDON has no membership-based expiry: its scope is a
page window, so products drift out of it naturally and the freshness limit is
CDON's only expiry. Show the last successful refresh time; use a freshness
limit, default 48 hours for daily scans, to hide offers whose stock and price
can no longer be treated as current.

#### Main page

The main page has two parts, in this order:

1. **Watchlist.** Every in-stock product whose movie is watched, or which is
   watched directly, regardless of price, cheapest first. This includes watched
   collections and unmatched products. This is the section the user cares about
   most, so it is always at the top and is never affected by the price limits or
   filters below. It is omitted entirely when empty rather than shown as an
   empty box.
2. **Everything else.** One filterable list of in-stock, non-ignored products,
   using the selected price limits. Products already shown in section 1 are
   not repeated here.

The intended session is: open the tab, check the watchlist section, scan the
list for interesting movies, ignore the ones not wanted or already owned, maybe
watch one or two, close the tab. Nothing else competes for attention on this
page: no stats tiles, no price-alert feed, no match queue, no cheapest
carousels, no per-store sections.

Every filter on section 2 is a query parameter so a view is bookmarkable. The
page must answer questions of this shape directly:

| Question                                     | Filters                        |
| -------------------------------------------- | ------------------------------ |
| Blu-ray at €10 or less and 4K at €20 or less | (no parameters, defaults)      |
| All movies at €10 or less                    | `max_bd=10&max_4k=10`          |
| Only 4K at €20 or less                       | `format=4k`                    |
| Blu-ray at €15 or less, one store            | `format=bd&max_bd=15&store=ax` |

Filters: `max_bd` and `max_4k` (euros, decimals allowed, converted to cents),
`format` (`bd`, `4k`, any), `store`, `condition` (`new`, `used`, any), and a
title search `q`. `max_dvd` is reserved for the same pattern but unused in v1.
Omitted maximum price parameters use the hardcoded €10 / €20. Both format
limits apply when viewing all formats. Changing a format filter retains the
selected price limits. These query parameters affect section 2 only; section 1
ignores price entirely.

The default view includes in-stock products within these limits, cheapest first,
with a stable title and product-ID order for equal prices.
Filter changes apply without a page reload; a plain form submit is acceptable
as the fallback.

Each row shows: title (matched TMDB title when available, otherwise raw store
title; collections always use the store title), format, condition, store, current
price, and an outbound link to the exact store edition
including its fragment. Rows expose two actions: ignore and watch.

Ignore hides the product from every list. Ignore applies to the TMDB movie when
the product is matched, so every edition across stores disappears together; for
unmatched products and collections it applies to the single store product. Watch
adds the movie (or, for unmatched products and collections, the store product)
to the watchlist. Both are one click with no confirmation and no page reload.
Ignore and watch are mutually exclusive for the same movie; applying one removes
the other.

When an unmatched product receives a movie match, transfer its watch or ignore
preference to that movie. If this conflicts with another preference for the same
movie, the latest explicit user action wins. Retain action timestamps and the
originating product so a corrected match can be reconciled without losing user
intent. Collections retain product-level preferences. Ignored entries remain
accessible on the ignored management page for unignore.

#### Secondary pages

Everything else lives behind a small nav, not on the main page: the ignored list
with unignore, the manual match review queue for in-stock single-movie products
without a confirmed TMDB match (whether or not candidates were found),
the full watchlist (watched movies with their current cheapest in-stock
price per format and store, plus directly watched products and collections,
with unwatch), a per-product price
history view, and a status page showing the
last successful run per store, run completeness, and product counts. The
freshness limit is shown on the status page. The front-page price controls show
the selected limits.

Keep watched entries with no eligible in-stock products on the watchlist
management page, labelled "No in-stock offers" and with an unwatch action.
This preserves the user's saved preference without displaying unavailable
products as shopping results. Such entries never appear on the front page.

All shopping views exclude unavailable, preorder, supplier-order, and unknown-
availability products. Unmatched in-stock products remain in the main list under
their raw title; their match status is visible only on the secondary pages.

## Data model

Keep one local SQLite database, created fresh. Delete the existing database
file; do not write migration code for it. Use these logical entities:

| Entity                     | Responsibility                                                                                           |
| -------------------------- | -------------------------------------------------------------------------------------------------------- |
| Store                      | Stable store key, name, adapter configuration                                                            |
| Crawl run and raw snapshot | Fetch evidence, completion, scope, parser provenance                                                     |
| Store product              | Unique store/product ID, raw title, edition, condition, format, collection flag, optional TMDB link      |
| Price observation          | Product, run, observation time, current price, optional regular price, currency, stock, snapshot         |
| Movie metadata             | TMDB identity, optional IMDb ID, and cached metadata shared across store products                        |
| Match state                | Candidate evidence, automatic/manual decision, retry or review state                                     |
| User preference            | Watch or ignore by movie or product, explicit action timestamp, and originating product where applicable |

Product uniqueness is store-scoped: (store, store product ID). Design the
schema for the new pipeline directly rather than adapting the current tables.
Existing models, repository queries, API models, and templates may be rewritten
or removed freely; the CDON adapter is reimplemented against the new contract.

Schema changes after this point use versioned migrations with explicit failures,
replacing the current pattern of suppressing all schema errors. All product
lookups, monitoring, API models, and stock expiration include store identity.
TMDB matching targets movies only. TV packages and multi-title boxes are
collections and remain unmatched products in this scope.

## Implementation order and acceptance checks

1. Capture representative Äx fixtures and implement the raw archive and standalone
   crawler. Verify pagination, edition IDs, failures, and the strict offer scope.
2. Implement the offline Äx parser and shared product contract. Test new and used
   Blu-ray/4K, combined formats, DVD exclusion, collections, localized prices,
   missing regular prices, and each stock state. Include supplier-stock examples
   so orderable products do not count as confirmed in stock.
3. Create the store-aware schema and idempotent import. Test ID collisions
   across stores, replay, older snapshots, and incomplete runs. Adapt CDON to
   the same crawl/parse separation.
4. Implement independent TMDB matching for single movies. Test title cleanup,
   ambiguous remakes, missing years, retries, manual overrides, and collection
   exclusion. Spot-check accepted matches by hand; no golden set in v1.
5. Implement the current-price query and UI. Test Blu-ray at €10.00 and €10.01,
   4K at €20.00 and €20.01, combined 4K/Blu-ray editions using the 4K limit,
   collections using the whole product price, new and used products, and a first
   observation with no previous or regular price. Verify unchanged prices on
   separate crawls remain in history, replay adds no duplicate observations,
   hidden stock states stay hidden, and expired offers do not qualify.
   Verify the watchlist section appears first and only when non-empty, ignores
   price limits and filters, and does not duplicate rows in the main list; each
   question in the main-page filter table; ignore and watch without reload
   (matched product affects every edition, unmatched affects one); matching review,
   collection titles, and edition links through Playwright against an isolated
   fixture database. Test preference transfer after matching, conflicting actions,
   corrected matches, and watched entries with no in-stock products.
6. Add CLI commands and the Docker image. Keep daily refresh and manual
   execution as defaults. Run each stage independently, with a convenience
   refresh command that performs crawl, parse, and match in sequence per store.
   Scheduling is one mechanism per deployment: the in-process scheduler inside
   the container by default, or host cron calling the refresh command with the
   in-process scheduler disabled. Remove fly.io files. Test stage failure
   handling, concurrent-run exclusion, UI reads during an import, and normal
   startup preserving the new database and preferences.
7. Update `CLAUDE.md` (commands, endpoints, architecture) and rewrite
   `ai-docs/crawler-investigation.md` for the adapter layout and Docker
   deployment.

Finish each implementation increment with appropriate tests, `task lint`, and
`task build`. Web changes also require Playwright verification.

## Deferred work

Sale percentages, historical comparison metrics, and their UI controls are
deferred. Preserve price history, but do not define or implement their formulas
in this version. Collection membership linking, IMDb/OMDb
API integration, checkout automation, shipping-inclusive comparisons, collecting
the entire Äx catalog, raw-archive cleanup, Äx detail-page fetching, a
labelled TMDB calibration set, notifications of any kind, and renaming the
project are outside this plan.
