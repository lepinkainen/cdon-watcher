# Äx offer fixtures

Captured with ordinary HTTP GET requests on 2026-09-21. The gzip files contain
the full response bodies, without formatting or cleanup.

- `offers-page-1.html.gz`: <https://www.levykauppax.fi/leffat/offer/>, 96 rows.
- `offers-page-14.html.gz`: <https://www.levykauppax.fi/leffat/offer/?p2=14>, 39 rows.

These captures cover pagination, edition fragments, DVD exclusion, Blu-ray,
combined UHD/Blu-ray editions, regular prices, and several stock descriptions.
Counts describe these fixtures only. Tests derive smaller pages from a captured
row to exercise failures and pagination changes without network requests.

## Search results

Captured 2026-11-11 with plain HTTP GET, for phase 2 targeted searches.

- `search-innerspace.html.gz`: <https://www.levykauppax.fi/v2/search/?q=Innerspace>,
  5 rows: 4K, DVD, two Blu-rays and a 7" single.
- `search-oldboy.html.gz`: <https://www.levykauppax.fi/v2/search/?q=Oldboy>,
  10 rows mixing new and used Blu-ray, 4K, DVD and a CD.

Search pages use the same `li.hproduct` rows as the offer listing, under an
`<h1>Haku</h1>` heading, and mix in music (`/artist/`, `/single/` links).
