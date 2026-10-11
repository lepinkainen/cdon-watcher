# Äx offer fixtures

Captured with ordinary HTTP GET requests on 2026-09-21. The gzip files contain
the full response bodies, without formatting or cleanup.

- `offers-page-1.html.gz`: <https://www.levykauppax.fi/leffat/offer/>, 96 rows.
- `offers-page-14.html.gz`: <https://www.levykauppax.fi/leffat/offer/?p2=14>, 39 rows.

These captures cover pagination, edition fragments, DVD exclusion, Blu-ray,
combined UHD/Blu-ray editions, regular prices, and several stock descriptions.
Counts describe these fixtures only. Tests derive smaller pages from a captured
row to exercise failures and pagination changes without network requests.
