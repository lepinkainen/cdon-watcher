"""Background scheduler running daily catalog refresh + watchlist check.

Runs inside the FastAPI process so a single fly.io Machine + volume can host
both the 24/7 web service and the daily scrape without volume contention.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime

from .config import CONFIG
from .monitoring_service import PriceMonitor

logger = logging.getLogger(__name__)


async def _run_once() -> None:
    """Run a full catalog crawl followed by a watchlist price check."""
    from .cdon_scraper import CDONScraper

    scan_mode = CONFIG.get("scan_mode", "slow")
    max_pages = int(os.environ.get("MAX_PAGES_PER_CATEGORY", "10"))

    logger.info(
        "Scheduler tick at %s — crawl mode=%s, pages/category=%d",
        datetime.now().isoformat(),
        scan_mode,
        max_pages,
    )

    scraper = CDONScraper()
    try:
        await scraper.crawl_category(
            "https://cdon.fi/elokuvat/",
            max_pages=max_pages,
            scan_mode=scan_mode,
            format_filter="blu-ray",
        )
        await scraper.crawl_category(
            "https://cdon.fi/elokuvat/",
            max_pages=max_pages,
            scan_mode=scan_mode,
            format_filter="4k",
        )
    except Exception:
        logger.exception("Crawl step failed")

    try:
        monitor = PriceMonitor()
        await monitor.check_watchlist_prices()
    except Exception:
        logger.exception("Watchlist check failed")

    logger.info("Scheduler tick done at %s", datetime.now().isoformat())


async def _scheduler_loop(interval_seconds: float, initial_delay_seconds: float) -> None:
    if initial_delay_seconds > 0:
        logger.info("Scheduler sleeping %.0fs before first run", initial_delay_seconds)
        await asyncio.sleep(initial_delay_seconds)

    while True:
        try:
            await _run_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Unexpected scheduler error")
        await asyncio.sleep(interval_seconds)


def start_scheduler() -> asyncio.Task[None] | None:
    """Start the scheduler if RUN_SCHEDULER=true. Returns the task or None."""
    if os.environ.get("RUN_SCHEDULER", "false").lower() != "true":
        logger.info("Scheduler disabled (set RUN_SCHEDULER=true to enable)")
        return None

    interval_hours = float(os.environ.get("SCHEDULER_INTERVAL_HOURS", "24"))
    initial_delay = float(os.environ.get("SCHEDULER_INITIAL_DELAY_SECONDS", "300"))

    logger.info(
        "Starting daily scheduler (interval=%.1fh, initial_delay=%.0fs)",
        interval_hours,
        initial_delay,
    )
    return asyncio.create_task(
        _scheduler_loop(interval_hours * 3600.0, initial_delay),
        name="cdon-watcher-scheduler",
    )
