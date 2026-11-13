# Äx offer fixtures

Captured with ordinary HTTP GET requests on 2026-09-21. The gzip files contain
the full response bodies, without formatting or cleanup.

- `offers-page-1.html.gz`: <https://www.levykauppax.fi/leffat/offer/>, 96 rows.
- `offers-page-14.html.gz`: <https://www.levykauppax.fi/leffat/offer/?p2=14>, 39 rows.

These two unfiltered captures predate the format passes and now serve the
parser tests only; the adapter rejects unfiltered offer URLs.

## Format passes

Captured 2026-11-13 with plain HTTP GET, during a storewide -10% sale. Each is
page 1 of a cheapest-first pass.

- `offers-blu-page-1.html.gz`: <https://www.levykauppax.fi/leffat/offer/?f2=blu&o2=p>,
  100 rows, paginator up to page 181.
- `offers-uhd-page-1.html.gz`: <https://www.levykauppax.fi/leffat/offer/?f2=uhd&o2=p>, 100 rows.
- `offers-ultrasb-page-1.html.gz`: <https://www.levykauppax.fi/leffat/offer/?f2=ultrasb&o2=p>,
  100 rows, one without a price ("Tuote ei ole myynnissä"), `2ULTRASB + 2BLU` codes.
- `offers-blusb-page-1.html.gz`: <https://www.levykauppax.fi/leffat/offer/?f2=blusb&o2=p>,
  35 rows, no paginator, `2blusb` codes.

The unfiltered captures cover pagination, edition fragments, DVD exclusion, Blu-ray,
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
