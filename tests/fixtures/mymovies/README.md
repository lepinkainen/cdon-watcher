# MyMovies fixtures

Captured 2026-11-12 with plain HTTP POSTs to
`https://www.mymovies.fi/ajax/hae-tuotteet2.php`, sent with a desktop Chrome
User-Agent (the site answers 403 to others). Each gzip file holds the endpoint's
JSON body unchanged: `html` (the result cards), `pagination` and `total`.
Requests send the search form as multipart fields; see
`ingestion/mymovies.py` for the fixed ones.

## Catalogue listing

Empty query, `saatavuus=1` (in stock only), Blu-ray and 4K UHD, title search:

- `listing-page-1.json.gz`: `page=1`, 60 cards of 2,999; paginator links to page 50.
- `listing-page-50.json.gz`: `page=50`, the last page, 59 cards.

## Searches

`saatavuus=0` (any availability):

- `search-looper.json.gz`: `q=looper`, Blu-ray and 4K, title only (the request
  the watcher sends): the Looper Blu-ray (14092) and 4K UHD (36119).
- `search-looper-all-formats.json.gz`: `q=looper` with DVD included and
  `hakukentta=kaikki` (cast and crew too), 14 cards. Covers DVD, `Kiinteä hinta`,
  green, yellow and red stock dots, cards with no buy button, and `Uusi: -`
  (no new copy).
- `search-no-match.json.gz`: `q=zzqxnotamovie`: `total` 0 and the
  "Ei tuloksia valituilla ehdoilla." placeholder.

Counts describe these fixtures only.
