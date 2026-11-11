# cdon-watcher

Tracks Blu-ray and 4K UHD offers at two Finnish stores, [Levykauppa Äx](https://www.levykauppax.fi/)
and [CDON](https://cdon.fi/), and shows the cheap ones in a small web app. Once a
day it reads the stores' movie listings, records prices in SQLite and matches each
product to a movie on [TMDB](https://www.themoviedb.org/).

It is a single-user tool with no login, meant to run on your own machine or a
private server.

## Pages

- **`/`**: in-stock offers under €15 (Blu-ray) or €20 (4K), minus movies you
  already own. Filter by format, store, condition, price or title. Each offer can
  be ignored or added to your wishlist.
- **`/in-stock`**: offers for movies on your wishlist, at any price.
- **`/wishlist`**: each wished movie with its offers and store searches.
- **`/queue`**: products that TMDB matching couldn't place, to match by hand.
- **`/products/<id>`**: price history for one product.
- **`/ignored`**, **`/status`**: ignored products; last refresh per store.

## moviecatalog

Owned movies and the wishlist come from moviecatalog, a separate app. Set
`MOVIECATALOG_URL` and each refresh pulls both lists, hides owned movies and
searches both stores for every wished movie. Without it, every offer shows and
there are no wishlist searches.

moviecatalog in turn reads offers from `GET /api/v2/offers?tmdb_id=…`.

## Run locally

Needs [uv](https://docs.astral.sh/uv/) and [Task](https://taskfile.dev/).

```bash
task install                             # dependencies + Playwright Chromium
cp .env.example .env                     # set TMDB_API_KEY, optionally MOVIECATALOG_URL
uv run python -m cdon_watcher refresh    # first crawl
uv run python -m cdon_watcher web        # http://localhost:8080
```

CDON blocks plain HTTP, so its listings are fetched with headless Chromium.

## Run in Docker

```bash
cp .env.example .env    # set TMDB_API_KEY, optionally MOVIECATALOG_URL
docker compose up -d --build
```

One container serves the web app on port 8080 and runs the refresh once a day.
The database and saved listing pages live in the `data` volume. To schedule the
refresh from host cron instead, set `RUN_SCHEDULER=false` and run
`docker compose exec app python -m cdon_watcher refresh`.

## Configuration

All settings are environment variables; `.env.example` lists them with defaults.
The ones you are likely to set:

| Variable                 | Purpose                                                         |
| ------------------------ | --------------------------------------------------------------- |
| `TMDB_API_KEY`           | TMDB matching. Without it, products stay unmatched.             |
| `MOVIECATALOG_URL`       | Owned movies and wishlist (see above).                          |
| `STORES`                 | Stores to refresh, default `ax,cdon`.                           |
| `MAX_PAGES_PER_CATEGORY` | CDON listing pages to read per refresh, default 10.             |
| `SEARCH_DAILY_CAP`       | Wishlist search requests per store per day, default 100.        |
| `RUN_SCHEDULER`          | Daily refresh inside the web process (on by default in Docker). |

## Commands

```bash
uv run python -m cdon_watcher refresh [--store ax|cdon]   # sync, crawl, import, match
uv run python -m cdon_watcher refresh --search-only        # sync + wishlist searches, no crawl
uv run python -m cdon_watcher sync                        # pull lists from moviecatalog
uv run python -m cdon_watcher search --store cdon         # wishlist searches only
uv run python -m cdon_watcher match                       # TMDB matching only
```

`--help` on any command lists the rest, including the individual refresh stages.

## Development

```bash
task test        # unit tests, no network
task test-live   # checks the live store pages still parse
task build       # tests + lint
```

Architecture and conventions are in [`CLAUDE.md`](CLAUDE.md); the design is in
[`docs/09_multi_store_plan.md`](docs/09_multi_store_plan.md). When a store
changes its pages, see
[`ai-docs/crawler-investigation.md`](ai-docs/crawler-investigation.md).
