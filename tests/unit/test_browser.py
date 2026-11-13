"""BrowserFetcher page handling against a fake Playwright page. No browser, no network."""

from playwright.sync_api import TimeoutError as PlaywrightTimeout

from shelfwatch.ingestion.browser import BrowserFetcher

PAGE = b'<html><script id="__NEXT_DATA__">{}</script></html>'


class FakePage:
    """Follows Playwright: a <script> is attached but never visible."""

    url = "https://cdon.fi/elokuvat/"

    def __init__(self):
        self.waited_out = False

    def goto(self, url, **kwargs):
        return type("R", (), {"status": 200})()

    def title(self):
        return "Elokuvat | CDON"

    def evaluate(self, script):
        return "not-found"

    def wait_for_selector(self, selector, *, state="visible", timeout=30000):
        if selector.startswith("script") and state == "visible":
            self.waited_out = True  # the real page sits here for the whole timeout
            raise PlaywrightTimeout(f"waiting for {selector} to be visible")

    def content(self):
        return PAGE.decode()


def test_next_data_wait_returns_once_the_script_is_attached():
    fetcher = BrowserFetcher.__new__(BrowserFetcher)
    fetcher._page = FakePage()
    fetcher.challenge_timeout = 30.0
    fetcher.content_timeout_ms = 20000
    fetcher.settle_seconds = 0
    response = fetcher("https://cdon.fi/elokuvat/")
    assert response.status == 200 and response.body == PAGE
    assert not fetcher._page.waited_out
