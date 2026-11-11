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
