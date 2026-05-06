# Investigating + Updating the CDON Crawler

Audience: AI agents (or humans) debugging a regression in `listing_crawler.py`
or `product_parser.py`. CDON's site structure changes without notice and the
scheduler runs daily on fly.io, so a silent failure means stale data until
someone notices.

This doc is a runbook. Follow it top-to-bottom when something breaks.

---

## 1. Decide what's broken

Run the live regression suite first — it pinpoints which layer failed:

```bash
task test-live
# or:
PYTHONPATH=./src uv run pytest tests/integration/test_live_cdon_pages.py -v
```

Layer mapping:

| Failing test                               | Likely layer       |
| ------------------------------------------ | ------------------ |
| `test_listing_page_shape[...]`             | listing crawler    |
| `test_pagination_increases_url_count`      | pagination         |
| `test_can_paginate_three_pages`            | pagination         |
| `test_product_page_fields[...]`            | product parser     |
| `test_invalid_product_url_returns_none`    | product parser     |
| `test_listing_to_product_pipeline`         | both layers        |

Don't proceed to step 2 until you know which layer to inspect.

---

## 2. Live page inspection with Playwright MCP

Playwright MCP is the fastest tool for a structural inspection. It lets you
navigate, run JS in-page, and snapshot the DOM without writing a script.

### 2a. Common probes

Navigate, then run these via `browser_evaluate`. Each is one-shot, copy-paste.

**Count product links + grab pagination indicator:**

```js
() => {
  const links = Array.from(document.querySelectorAll('a[href*="/tuote/"]'))
    .map(a => a.getAttribute('href'));
  const sivu = (document.body.innerText.match(/Sivu\s+\d+\/\d+/i) || [])[0];
  return {
    count: links.length,
    unique: [...new Set(links)].length,
    sample: links.slice(0, 3),
    sivu,
  };
}
```

CDON shows `Sivu N/M` where M is the total page count. `Sivu 1/1` with a
non-trivial URL = pagination is being ignored server-side.

**Find pagination/load-more controls:**

```js
() => {
  const candidates = Array.from(document.querySelectorAll('button, a'))
    .filter(el => /näytä lisää|load more|seuraava|sivu/i.test(el.textContent || ''))
    .map(el => ({ tag: el.tagName, text: el.textContent.trim().slice(0, 60) }));
  const paramHrefs = Array.from(document.querySelectorAll('a'))
    .map(a => a.getAttribute('href'))
    .filter(h => h && /(page=|p=|offset=|sivu=)/i.test(h));
  return { candidates, paramHrefs: [...new Set(paramHrefs)].slice(0, 10) };
}
```

**Check infinite-scroll behavior:**

```js
async () => {
  const wait = ms => new Promise(r => setTimeout(r, ms));
  const counts = [document.querySelectorAll('a[href*="/tuote/"]').length];
  for (let i = 0; i < 6; i++) {
    window.scrollTo(0, document.body.scrollHeight);
    await wait(1500);
    counts.push(document.querySelectorAll('a[href*="/tuote/"]').length);
  }
  return { counts };
}
```

Flat counts = no infinite scroll. Growing counts = lazy-load on scroll
required (and the crawler must scroll, not just `goto`).

**Read Next.js page state:**

```js
() => {
  const node = document.getElementById('__NEXT_DATA__');
  if (!node) return null;
  return JSON.stringify(JSON.parse(node.textContent)).slice(0, 4000);
}
```

CDON is a Next.js app — `__NEXT_DATA__` often reveals canonical URLs, page
counts, and whether facets/pagination round-tripped to the server.

### 2b. The cookie banner trap

CDON loads a Didomi consent overlay on first visit. While it's up, click and
scroll events targeted at the underlying grid get intercepted, and on some
URL combos the server returns a stripped-down `Sivu 1/1` response. Always
dismiss it before measuring anything:

```js
() => {
  const sel = document.querySelector(
    '#didomi-notice-agree-button, button.didomi-button-highlight'
  );
  if (sel) { sel.click(); return 'clicked'; }
  const fallback = Array.from(document.querySelectorAll('button'))
    .find(b => /hyväksy/i.test(b.textContent || ''));
  if (fallback) { fallback.click(); return 'clicked-fallback'; }
  return 'not-found';
}
```

`ListingCrawler._dismiss_cookie_banner` does this in production — keep the
selectors there in sync with whatever Didomi ships next.

### 2c. Known traps already discovered

Document new traps here when you find them. Existing ones:

- **Facet + page combo broken.** URLs like
  `/elokuvat/?facets=property_preset_media_format%3Ablu-ray&q=&page=2` always
  return the first 15 products with `Sivu 1/1`. Workaround: crawl plain
  `/elokuvat/?page=N` and filter by URL slug regex. See
  `FORMAT_SLUG_PATTERNS` in `src/cdon_watcher/listing_crawler.py`.
- **Header carousel pollutes URL counts.** Top-of-page recommendations
  contribute the same ~5 product links on every page. When asserting "page
  N has new URLs", expect overlap from the carousel — require growth, not
  full distinctness.
- **Banner titles in `<h1>`.** Box-set landing pages cycle through marketing
  banners (`Elokuvaboksit, jotka luovat ikimuistoisia elokuvailtoja`).
  Always prefer `<meta property="og:title">` for the canonical product
  title; fall back to `<h1>` only if og is missing.

---

## 3. Reproduce in Python (when MCP isn't enough)

Sometimes you need to confirm the crawler's actual behavior, not just what
the page renders manually. Drop a temp script next to the crawler:

```python
# /tmp/probe_listing.py
import asyncio
from cdon_watcher.listing_crawler import ListingCrawler

async def main():
    crawler = ListingCrawler()
    urls = await crawler.crawl_category(
        "https://cdon.fi/elokuvat/",
        max_pages=3,
        scan_mode="fast",
        format_filter="blu-ray",
    )
    print(f"got {len(urls)} URLs")
    for u in urls[:5]:
        print(" -", u)

asyncio.run(main())
```

Run with: `PYTHONPATH=./src uv run python /tmp/probe_listing.py`

Or shell into the production fly.io machine:

```bash
fly ssh console -a cdon-watcher
python -m cdon_watcher crawl   # uses the same code path as the scheduler
```

---

## 4. Updating the crawler

When you've identified a fix, change one of these places:

| Symptom                                    | File                                                          |
| ------------------------------------------ | ------------------------------------------------------------- |
| Cookie banner selector changed             | `listing_crawler.py::_dismiss_cookie_banner`                  |
| Pagination param renamed                   | `listing_crawler.py::crawl_category` (URL construction loop)  |
| New format (e.g. SteelBook) needs filter   | `listing_crawler.py::FORMAT_SLUG_PATTERNS`                    |
| Title selector / banner blocklist          | `product_parser.py::_extract_title`, `_BANNER_MARKERS`        |
| Format detection heuristic                 | `product_parser.py::_determine_format`                        |
| Price selector changed                     | `product_parser.py::_extract_price`                           |
| Production-year DOM structure changed      | `product_parser.py::_extract_production_year`                 |
| Category URLs themselves moved             | `cli.py::run_crawl`, `scheduler.py::_run_once`                |

After editing, this is the validation loop — run it every time:

```bash
task lint                  # ruff + mypy
PYTHONPATH=./src uv run pytest tests/unit/ --timeout=30 -q
task test-live             # the live regression suite
```

All three must pass. Don't deploy on partial green.

### Adding new live coverage

If you discovered a regression that the existing live tests didn't catch,
**add a test** before fixing the bug. The fix without the test invites a
silent re-regression next time CDON changes.

Tests live in `tests/integration/test_live_cdon_pages.py`. Pattern:

- One test = one site-shape invariant.
- Use `_skip_if_unreachable` (autouse fixture) — it's already wired up.
- Assert hard on shape (formats, URL patterns, counts), tolerate soft on
  exact values that may legitimately drift (specific product IDs, prices).
- Mark with `@pytest.mark.timeout(N)` — Playwright tests stall sometimes.

Example skeleton:

```python
@pytest.mark.asyncio
@pytest.mark.timeout(120)
async def test_my_invariant(listing_crawler):
    urls = await listing_crawler.crawl_category(
        CATEGORY_URL, max_pages=1, format_filter="blu-ray"
    )
    assert len(urls) >= 5
```

---

## 5. Deploying the fix

After local green, redeploy fly.io:

```bash
fly deploy
fly logs -a cdon-watcher    # watch scheduler tick — first run is ~5 min after boot
```

The scheduler tick logs `Scheduler tick at <iso-ts> — crawl mode=…` at
start and `Scheduler tick done at <iso-ts>` at end. If the second log line
never appears, the crawl is stuck — most likely Playwright lockup; recheck
selectors or restart the machine.

---

## 6. References

- `src/cdon_watcher/listing_crawler.py` — Playwright listing scraper.
- `src/cdon_watcher/product_parser.py` — requests + BS4 product page parser.
- `src/cdon_watcher/scheduler.py` — daily background task in the FastAPI
  process; runs both crawls + watchlist check.
- `tests/integration/test_live_cdon_pages.py` — live regression suite.
- `fly.toml` — `RUN_SCHEDULER`, `SCHEDULER_INTERVAL_HOURS`,
  `MAX_PAGES_PER_CATEGORY`, `SCAN_MODE`.
