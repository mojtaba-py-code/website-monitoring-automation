"""Small, dependency-light helpers shared across the package."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import TypeVar

T = TypeVar("T")


def utcnow() -> datetime:
    """Timezone-aware current UTC time."""
    return datetime.now(timezone.utc)


def iso_now() -> str:
    """ISO-8601 UTC timestamp, second precision."""
    return utcnow().replace(microsecond=0).isoformat()


def human_duration(seconds: float) -> str:
    """Render a duration compactly (e.g. ``2d 03h``, ``1h 05m``, ``12s``)."""
    seconds = max(0.0, float(seconds))
    if seconds < 1:
        return f"{seconds * 1000:.0f} ms"
    minutes, sec = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    if days:
        return f"{days}d {hours:02d}h"
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {sec:02d}s"
    return f"{sec}s"


def human_size(num_bytes: float) -> str:
    """Render a byte count using binary units."""
    value = float(num_bytes)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024.0 or unit == "TiB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{value:.2f} TiB"  # pragma: no cover


def clamp(value: float, low: float, high: float) -> float:
    """Constrain ``value`` to ``[low, high]``."""
    return max(low, min(high, value))


async def retry_async(
    func: Callable[[], Awaitable[T]],
    *,
    attempts: int,
    backoff: float,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> T:
    """Await ``func`` with retries and exponential backoff.

    ``attempts`` is the number of *extra* tries after the first, so
    ``attempts=2`` means up to 3 invocations total. The final exception is
    re-raised if every attempt fails.
    """
    last_exc: BaseException | None = None
    for attempt in range(attempts + 1):
        try:
            return await func()
        except exceptions as exc:
            last_exc = exc
            if attempt < attempts:
                await asyncio.sleep(backoff * (2**attempt))
    # Unreachable unless every attempt failed. Raised explicitly rather than
    # asserted, because `python -O` strips asserts.
    if last_exc is None:  # pragma: no cover - defensive
        raise RuntimeError("retry_async exhausted its attempts without an exception")
    raise last_exc


def percentile(values: list[float], pct: float) -> float:
    """Return the ``pct`` percentile (0-100) of ``values`` (nearest-rank)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if pct <= 0:
        return ordered[0]
    if pct >= 100:
        return ordered[-1]
    rank = max(0, min(len(ordered) - 1, round((pct / 100) * len(ordered) + 0.5) - 1))
    return ordered[rank]
