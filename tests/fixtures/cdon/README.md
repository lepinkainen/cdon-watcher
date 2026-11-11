# CDON fixtures

Captured 2026-10-11 through headless Chromium (Playwright), because cdon.fi
serves a Cloudflare "Just a moment" challenge to plain HTTP clients. The gzip
files hold the rendered DOM after JavaScript, as `page.content()` returned it.

- `elokuvat-page-1.html.gz`: <https://cdon.fi/elokuvat/>, 48 articles.
- `elokuvat-page-2.html.gz`: <https://cdon.fi/elokuvat/?page=2>, 48 articles,
  `Sivu 2/208`.
- `product-saw-x.html.gz`: <https://cdon.fi/tuote/saw-x-blu-ray-f22e2fd9169a5422/>.
  Reference only; v1 does not fetch or parse product pages. Its page state has
  the description with `Julkaisuvuosi` and `Formaatti` lines for later use.

Listing pages embed `__NEXT_DATA__` whose `props.pageProps.serverData.articles`
carry title, slug, price, stock, condition and `preset_media_format`. Counts
describe these fixtures only.

## Search results

Captured 2026-11-11 for phase 2 targeted searches. Loading
`https://cdon.fi/s?q=<query>` in the browser renders an empty search page whose
script then POSTs to `search-bff.cdon.se/search/v2/result`. These files are
that response's JSON body, captured from the page's own request
(`BrowserFetcher.search`); nothing calls the API directly.

- `search-innerspace.json.gz`: `q=Innerspace`, 14 articles.
- `search-oldboy.json.gz`: `q=Oldboy`, 21 articles.
- `search-no-match.json.gz`: `q=xqzvbnm nothing here`, 48 of 13,733 loosely
  related articles. CDON never returns an empty result, so a search hit says
  nothing until it is checked against the wished movie.

Articles have the category-page shape, but most are marketplace listings
without `preset_media_format`, so the format comes from the title and slug.
Results mix in music, books and other categories.
