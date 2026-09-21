# Physical movie store database plan

Status: agreed scope and proposed implementation, 2026-09-21. This document
describes planned work; the application does not implement it yet.

## Agreed scope

- Keep CDON and add Levykauppa Äx, limited to
  <https://www.levykauppax.fi/leffat/offer/> and products discovered there.
- Include Blu-ray and 4K UHD, both new and used. Exclude DVD-only products.
  Keep steelbooks, combined 4K/Blu-ray releases, and multi-disc editions.
- Compare the current item price with the store's displayed crossed-out regular
  price. Exclude shipping. The default minimum discount is 20%, inclusive.
- Use TMDB for movie identity. No IMDb or OMDb API integration is required.
- Include collections using the original store title. Do not attempt movie
  matching or collection membership linking for them.
- Crawl, parse, and match eligible products regardless of stock status or
  discount. Only confirmed in-stock products appear in the shopping UI.
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
`PriceHistory` lacks a regular price. The deals query compares consecutive price
observations instead of measuring the current discount against a regular price.
Automatic TMDB lookup selects the first result, while manual review is tied to
watchlist and ignore actions. These responsibilities need separating.

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

### 1. Crawl raw data

Introduce a small store adapter interface with CDON and Äx implementations.
Adapters own URL discovery, pagination, and retrieval. The crawler may inspect
markup to discover links and eligible formats; it does not write normalized
products, calculate discounts, or call TMDB.

Save listing and relevant detail responses with a run ID, store, scope, requested
and final URL, fetch time, HTTP status, content hash, and body reference. Use a
run manifest and compressed response files under `data/raw/`. Preserve the
retrieved response separately from any rendered DOM used by a browser adapter.

Follow every offer page, with bounded retries and a delay between requests. A
manual page limit, missing page, repeated pagination loop, or failed required
detail fetch makes the run incomplete. A transient error page must not become an
empty catalog. Record counts and failure reasons for diagnosis.

### 2. Parse and import offline

Each store parser consumes saved responses and returns a shared product record.
It performs no HTTP requests or TMDB calls. Parsing and database import can run
again without crawling. Associate every normalized observation with its source
snapshot and parser version.

Normalize format, condition, and availability while preserving their raw text.
Retain the original title and a separate cleaned title for matching. Extract
edition identifiers, EAN, year, and descriptive metadata where present. A
multi-disc single movie must not be classified as a collection solely because it
contains more than one disc.

Use integer minor currency units for prices and an explicit currency. Preserve
both current and regular prices from the same observation. Reject invalid
prices; do not invent a regular price from the historical maximum. If listing
and detail data conflict, record the conflict and withhold deal eligibility
until the relevant edition's price and stock are unambiguous.

Import transactionally and idempotently. Replaying the same snapshot must not
append duplicate history or change its observed timestamp. Reprocessing an old
run must not replace newer current state. Parsing errors must not erase good
records or count as evidence that products disappeared.

### 3. Match movie identity

Run TMDB enrichment as a separate retryable stage after import. Reuse existing
TMDB search and manual review components, but remove the dependency on a
watchlist action. A TMDB outage must not interrupt crawling or parsing.

Use cleaned and alternate titles, production year, and other available evidence
to evaluate candidates. Do not confuse a disc release year with a movie's
production year. Accept an automatic match only with sufficient evidence and
separation from competing candidates. Otherwise store candidates and mark the
product ambiguous or unmatched. Calibrate matching against saved examples before
choosing a confidence threshold; popularity alone is not identity evidence.

Keep manual matches across future imports. Cache and reuse established matches
when edition identifiers or sufficient movie evidence agree. Collections have
an explicit `not_applicable` match status and never enter the matching queue.
Stock changes do not discard matches. Hidden products still receive automatic
matching, but uncertain hidden products do not require user attention.

### 4. Query sales and show the database

The sale finder is a database query or service, not another crawler. A qualifying
offer has a current, successfully parsed observation, confirmed stock, an
eligible format, a positive regular price, and a calculated discount of at least
the configured threshold. Evaluate the threshold before rounding for display.

For Äx, require active membership in the offer category. Only a successfully
completed and parsed run may mark previously seen offers inactive. Disappearance
means the offer ended or left scope, not that the product sold out. Partial runs
do not expire unseen products, and one store's run never expires another's.
Show the last successful refresh time; use a configurable freshness limit,
proposed default 48 hours for daily scans, to hide offers whose stock and price
can no longer be treated as current.

Default the UI to all qualifying in-stock offers with a 20% threshold. Show store,
raw edition title, matched movie title when available, format, condition, current
and regular prices, discount, and last checked time. Support store, format,
condition, collection, and title filters, with an optional existing watchlist
filter. Keep a database browsing view for in-stock products below the threshold.

Unmatched in-stock offers remain discoverable under their raw title with a clear
match status. Manual review is available for those products. Collections always
use the store title. All shopping views exclude unavailable and preorder
products. Store links retain the exact edition fragment.

## Data model and migration

Keep one local SQLite database. Use these logical entities:

| Entity                     | Responsibility                                                                                      |
| -------------------------- | --------------------------------------------------------------------------------------------------- |
| Store                      | Stable store key, name, adapter configuration                                                       |
| Crawl run and raw snapshot | Fetch evidence, completion, scope, parser provenance                                                |
| Store product              | Unique store/product ID, raw title, edition, condition, format, collection flag, optional TMDB link |
| Price observation          | Product, observation time, current and regular price, currency, stock, snapshot                     |
| Movie metadata             | TMDB identity and cached metadata shared across store products                                      |
| Match state                | Candidate evidence, automatic/manual decision, retry or review state                                |

Adapt the existing product and price tables rather than maintaining a parallel
database. Migrate all existing products to the CDON store and replace global
product-ID uniqueness with store-scoped uniqueness. Preserve internal product
IDs, price history, watchlists, ignored movies, and confirmed matches. Existing
history has an unknown regular price and must not be backfilled with a guessed
value. Unknown legacy stock is hidden until refreshed.

Back up the database before migration and test migration against a copy. Use
versioned migrations with explicit failures rather than suppressing all schema
errors. Update all product lookups, monitoring, API models, and stock expiration
to include store identity. Keep the existing TMDB movie/TV distinction intact;
multi-title collections remain unmatched products in this scope.

## Implementation order and acceptance checks

1. Capture representative Äx fixtures and implement the raw archive and standalone
   crawler. Verify pagination, edition IDs, failures, and the strict offer scope.
2. Implement the offline Äx parser and shared product contract. Test new and used
   Blu-ray/4K, combined formats, DVD exclusion, collections, localized prices,
   missing regular prices, and each stock state. Include supplier-stock examples
   so orderable products do not count as confirmed in stock.
3. Add store-aware schema migration and idempotent import. Test ID collisions
   across stores, replay, older snapshots, incomplete runs, and preserved CDON
   history and user decisions. Adapt CDON to the same crawl/parse separation.
4. Implement independent TMDB matching. Test title cleanup, ambiguous remakes,
   missing years, retries, manual overrides, and collection exclusion. Check a
   representative sample of accepted matches for correctness.
5. Implement the discount query and UI. Test exactly 20%, just below 20%, missing
   reference prices, hidden stock states, used products, and expired offers.
   Verify filters, matching review, collection titles, and edition links through
   Playwright against an isolated fixture database.
6. Wire the stages into the existing scheduler and CLI. Keep daily refresh and
   manual execution as defaults. Run each stage independently, with a convenience
   refresh command that performs crawl, parse, and match in sequence per store.

Finish each implementation increment with appropriate tests, `task lint`, and
`task build`. Web changes also require Playwright verification. Do not modify
`llm-shared`.

## Deferred work

Collection membership linking, IMDb/OMDb API integration, checkout automation,
shipping-inclusive comparisons, collecting the entire Äx catalog, and renaming
the project are outside this plan. Existing notifications are not the primary
workflow and do not need new channels for this addition.
