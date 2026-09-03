"""Continuous scheduler.

Runs one asyncio task per enabled target, each looping on the target's own
interval, plus a periodic history-retention purge. Designed to run forever until
cancelled (Ctrl+C); every iteration is isolated so one failing target never
stops the others.

For OS-native scheduling instead, :func:`cron_line` / :func:`windows_task_command`
emit ready-to-use crontab / Task Scheduler snippets that invoke ``webmon check``.
"""

from __future__ import annotations

import asyncio

from .config import Target
from .logger import get_logger
from .monitor import MonitorService

logger = get_logger("scheduler")


class SchedulerService:
    """Drives periodic monitoring of every enabled target."""

    def __init__(self, monitor: MonitorService) -> None:
        self._monitor = monitor
        self._settings = monitor.settings

    def _interval(self, target: Target) -> int:
        return target.interval_seconds or self._settings.defaults.interval_seconds

    async def _target_loop(self, target: Target) -> None:
        interval = self._interval(target)
        logger.info("Scheduling '%s' every %ds", target.name, interval)
        while True:
            try:
                result = await self._monitor.check_target(target)
                await self._monitor.process(target, result)
            except asyncio.CancelledError:
                raise
            except Exception:  # never let one target kill its loop
                logger.exception("Monitoring loop error for %s", target.name)
            await asyncio.sleep(interval)

    async def _purge_loop(self) -> None:
        while True:
            await asyncio.sleep(6 * 3600)  # every 6 hours
            try:
                removed = self._monitor.purge_old()
                if removed:
                    logger.info("Purged %d old history rows", removed)
            except Exception:  # pragma: no cover - defensive
                logger.exception("History purge failed")

    async def run(self) -> None:
        """Run all target loops until cancelled."""
        targets = self._settings.enabled_targets()
        if not targets:
            logger.warning("No enabled targets; scheduler idle.")
            return
        tasks = [asyncio.create_task(self._target_loop(t)) for t in targets]
        if self._settings.database.enabled:
            tasks.append(asyncio.create_task(self._purge_loop()))
        logger.info("Scheduler started with %d target loop(s).", len(targets))
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:  # pragma: no cover - shutdown path
            for task in tasks:
                task.cancel()
            raise


def cron_line(command: str, minutes: int = 5) -> str:
    """Return a crontab line running ``command`` every ``minutes`` minutes."""
    if minutes >= 60 and minutes % 60 == 0:
        return f"0 */{minutes // 60} * * * {command}"
    return f"*/{minutes} * * * * {command}"


def windows_task_command(name: str, command: str, minutes: int = 5) -> str:
    """Return a ``schtasks`` command that runs ``command`` every N minutes."""
    return (
        f'schtasks /Create /TN "{name}" /TR "{command}" '
        f"/SC MINUTE /MO {minutes} /F"
    )
