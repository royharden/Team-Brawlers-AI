"""AttackScheduler — APScheduler boilerplate (master plan §8.1)."""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler


class AttackScheduler:
    """FIFO + priority queue for AttackJobs, with APScheduler hooks for cron runs."""

    def __init__(self) -> None:
        self._scheduler: AsyncIOScheduler = AsyncIOScheduler()

    def start(self) -> None:
        """Start the underlying scheduler. Jobs land in Phase 1."""
        self._scheduler.start()

    def shutdown(self) -> None:
        """Stop the scheduler cleanly."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
