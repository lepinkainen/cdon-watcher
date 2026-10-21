"""Browser-backed fetcher for stores that require JavaScript rendering."""

import time
from typing import Any

from playwright.sync_api import Error as PlaywrightError

from .crawler import FetchError, Response

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)
CHALLENGE_TITLE = "just a moment"
COOKIE_BANNER_JS = """
() => {
  const sel = document.querySelector('#didomi-notice-agree-button, button.didomi-button-highlight');
  if (sel) { sel.click(); return 'clicked'; }
  const fallback = Array.from(document.querySelectorAll('button'))
    .find(b => /hyväksy/i.test(b.textContent || ''));
  if (fallback) { fallback.click(); return 'clicked-fallback'; }
  return 'not-found';
}
"""


class BrowserFetcher:
    """Fetch pages through headless Chromium and return the rendered HTML.

    Waits out the Cloudflare interstitial, dismisses the cookie banner, and
    waits for the Next.js page state before snapshotting the DOM. One browser
    context is reused for the whole run so the challenge is solved once.
    """

    def __init__(
        self,
        *,
        challenge_timeout: float = 30.0,
        content_timeout_ms: int = 20000,
        settle_seconds: float = 1.0,
    ) -> None:
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        self._context = self._browser.new_context(
            user_agent=USER_AGENT,
            locale="fi-FI",
            timezone_id="Europe/Helsinki",
            viewport={"width": 1920, "height": 1080},
        )
        self._context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        self._page = self._context.new_page()
        self.challenge_timeout = challenge_timeout
        self.content_timeout_ms = content_timeout_ms
        self.settle_seconds = settle_seconds

    def __call__(self, url: str) -> Response:
        try:
            return self._fetch(url)
        except PlaywrightError as error:
            raise FetchError(str(error)) from error

    def _fetch(self, url: str) -> Response:
        response: Any = self._page.goto(url, wait_until="domcontentloaded", timeout=45000)
        status = response.status if response is not None else 0
        deadline = time.monotonic() + self.challenge_timeout
        while CHALLENGE_TITLE in self._page.title().lower():
            if time.monotonic() > deadline:
                return Response(self._page.url, 403, self._page.content().encode(), True)
            status = 200  # The interstitial's 403/503 is stale once the challenge resolves.
            time.sleep(1.0)
        try:
            self._page.evaluate(COOKIE_BANNER_JS)
        except Exception:  # noqa: BLE001 - banner dismissal is best effort
            pass
        try:
            self._page.wait_for_selector("script#__NEXT_DATA__", timeout=self.content_timeout_ms)
        except Exception:  # noqa: BLE001 - adapter validation reports a missing state
            pass
        time.sleep(self.settle_seconds)
        return Response(self._page.url, status, self._page.content().encode(), True)

    def close(self) -> None:
        self._context.close()
        self._browser.close()
        self._playwright.stop()
