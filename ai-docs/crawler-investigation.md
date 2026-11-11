# Investigating a broken store adapter

Audience: AI agents (or humans) debugging a regression in the Äx or CDON
ingestion. Both sites change without notice and the refresh runs daily, so a
silent failure means stale data until the status page shows it.

Follow top to bottom.

---

## 1. Decide what broke

```bash
task test-live        # tests/integration/test_live_stores.py
```

| Failing test                         | Layer                                                               |
| ------------------------------------ | ------------------------------------------------------------------- |
| `test_ax_first_offer_page_shape`     | Äx HTTP fetch, `AxAdapter.discover`, `AxParser`                     |
| `test_cdon_first_listing_page_shape` | Cloudflare challenge, `BrowserFetcher`, `CdonAdapter`, `CdonParser` |

Then look at the evidence the last refresh left behind:

```bash
ls data/raw/<store>/            # numbered runs; highest is latest
cat data/raw/<store>/<run>/manifest.json | jq '.complete, .failures, .snapshots[].error'
uv run python -m cdon_watcher parse-raw --store <store>   # re-parse offline; shows row errors
```

`manifest.json` records every fetch (status, error, body file). `parsed.json`
records every row error. Nothing hits the network at this point, so iterate
on the parser against the saved run until it is clean.

The status page (`/status`) shows the last run per store, completeness and
error counts; a stale row there means the daily refresh is not importing.

---

## 2. Inspect the live page

### Äx

Plain HTTP works. Fetch one page and poke at it:

```bash
curl -sA "cdon-watcher/0.1" "https://www.levykauppax.fi/leffat/offer/?p2=2" > /tmp/ax.html
```

Shape the adapter expects (`ingestion/stores.py::AxAdapter`, `ax_parser.py`):

- `<h1>Elokuvat - Tarjoukset</h1>` on every page (error-page guard).
- `ul.list-products > li.hproduct` rows with `id="p-<digits>"`.
- Row: `a.fn[href]` title link whose fragment is the edition id,
  `span.type` media text (`Käytetty` prefix = used; `2 Blu-ray`, `4K ULTRA HD + BLU`),
  `span.price` with optional `<del>` regular price, `p.shipping` stock text
  (`in-stock` class), `.sticker-bottom-right` quantity (`Enää N kpl`),
  `dl` with `Julkaisuvuosi` / `Yhtiö`.
- `.pagination a[href]` links with `?p2=N`; `.active` marks the current page.

### CDON

Plain HTTP returns a Cloudflare "Just a moment" page. Use a browser. Quickest
is the Playwright MCP (`browser_navigate`, then `browser_evaluate`), or the
project's own fetcher:

```bash
PYTHONPATH=./src uv run python - <<'PY'
from cdon_watcher.ingestion.browser import BrowserFetcher
f = BrowserFetcher(); r = f("https://cdon.fi/elokuvat/?page=2"); f.close()
open("/tmp/cdon.html", "wb").write(r.body); print(r.status, len(r.body))
PY
```

Shape the adapter expects (`CdonAdapter`, `cdon_parser.py`):

- `script#__NEXT_DATA__` with `props.pageProps.pageName == "CategoryPage"`
  and `serverData.articles[]`.
- Article: `slug` ending in 16 hex chars (= product id), `title`,
  `price.amount`, `stock` (int), `publishState`, `classifications[condition]`,
  `properties[preset_media_format]` (`blu-ray` / `4k ultra hd` / `dvd`), `images[].url`.
- Visible `Sivu N/M` text; `N` must equal the requested page (loop guard).

Useful in-page probe:

```js
;() => {
  const d = JSON.parse(document.getElementById('__NEXT_DATA__').textContent)
  const a = d.props.pageProps.serverData.articles
  return {
    count: a.length,
    first: a[0],
    sivu: (document.body.innerText.match(/Sivu\s+\d+\/\d+/) || [])[0],
  }
}
```

### Known traps

- **CDON facet + page combo is broken.** `?facets=...&page=2` always returns
  page 1. Crawl plain `/elokuvat/?page=N` and filter formats client-side.
- **CDON product URLs can turn into category landing pages** (old items). Not
  an issue for v1 because product pages are never fetched.
- **CDON `classifications` can be empty**, giving `condition=unknown`. Fine.
- **Äx offer scope is the only expiry signal.** A complete Äx run that sees
  fewer products than before is not a bug by itself; a run with
  `complete=false` never expires anything.
- **Prettier breaks Jinja.** Templates are in `.prettierignore` on purpose.

---

## 3. Fix

| Symptom                               | Where                                                       |
| ------------------------------------- | ----------------------------------------------------------- |
| Challenge never resolves / status 403 | `ingestion/browser.py` (wait, UA, cookie banner JS)         |
| Pagination param or scope changed     | `stores.py::<Adapter>.page_number`, `.discover`             |
| Rows found but fields wrong           | `ax_parser.py` / `cdon_parser.py`                           |
| Format or condition text changed      | `normalize.py::format_from_text`, `ax_parser.parse_format`  |
| Price text changed                    | `normalize.py::parse_price_cents` / `amount_to_cents`       |
| Stock wording changed                 | `ax_parser.parse_availability`, `cdon_parser._availability` |
| Collection misclassified              | `box_set_detector.py` patterns                              |
| Products vanish from the UI           | `catalog/queries.py::_shoppable` (freshness, in-stock)      |

Then capture a fresh fixture (gzip of the body, note the date and counts in
`tests/fixtures/<store>/README.md`), add or adjust a unit test first, make it
pass, and run:

```bash
task build       # unit tests + lint
task test-live   # the live shape tests
```

Re-import the saved run without re-crawling: `uv run python -m cdon_watcher
refresh --store <store> --skip-crawl`.

---

## 4. Deploy

```bash
docker compose build && docker compose up -d
docker compose logs -f     # "Scheduler tick at …" / "Scheduler tick done at …"
```

If "done" never appears the crawl is stuck; the per-store `.refresh.lock` under
`data/raw/<store>/` is released when the process dies, so a restart is safe.
