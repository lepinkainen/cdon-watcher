"""In-process daily refresh. Runs inside the web app when RUN_SCHEDULER=true.

One scheduling mechanism per deployment: either this, or host cron calling
`python -m cdon_watcher refresh` with RUN_SCHEDULER unset.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from .config import CONFIG
from .refresh import describe, refresh_all

logger = logging.getLogger(__name__)


async def _run_once() -> None:
    logger.info("Scheduler tick at %s", datetime.now().isoformat())
    try:
        reports = await asyncio.to_thread(refresh_all)
        for report in reports:
            logger.info(describe(report))
    except Exception:
        logger.exception("Refresh failed")
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
    if not CONFIG["run_scheduler"]:
        logger.info("Scheduler disabled (set RUN_SCHEDULER=true to enable)")
        return None
    interval_hours = float(CONFIG["scheduler_interval_hours"])
    initial_delay = float(CONFIG["scheduler_initial_delay"])
    logger.info(
        "Starting scheduler (interval=%.1fh, initial_delay=%.0fs)", interval_hours, initial_delay
    )
    return asyncio.create_task(
        _scheduler_loop(interval_hours * 3600.0, initial_delay), name="cdon-watcher-scheduler"
    )
