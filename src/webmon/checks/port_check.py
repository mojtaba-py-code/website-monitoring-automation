"""TCP port reachability probe.

Attempts a TCP connection to each configured port and reports which are open,
with per-port connect latency. The check is DOWN if any configured port is
closed/unreachable.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from urllib.parse import urlparse

from ..config import Target
from ..models import CheckResult, Status
from .base import CheckContext


async def _probe_port(host: str, port: int, timeout: float) -> tuple[bool, float | None]:
    started = time.perf_counter()
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        writer.close()
        with contextlib.suppress(OSError, ConnectionError):  # close races are harmless
            await writer.wait_closed()
        return True, round((time.perf_counter() - started) * 1000.0, 2)
    except (TimeoutError, OSError):
        return False, None


async def check_port(target: Target, ctx: CheckContext) -> CheckResult:
    eff = ctx.effective(target)
    host = urlparse(target.url).hostname or ""
    ports = target.ports or ([443] if target.url.startswith("https") else [80])

    # SSRF policy applies to raw port probes too.
    try:
        await asyncio.to_thread(ctx.guard.validate, target.url)
    except Exception as exc:  # SecurityError
        return CheckResult(target=target.name, kind="port", status=Status.DOWN, message=str(exc))

    results = await asyncio.gather(*(_probe_port(host, p, eff.timeout) for p in ports))
    port_status = {
        str(port): {"open": ok, "latency_ms": latency}
        for port, (ok, latency) in zip(ports, results, strict=True)
    }
    open_ports = [p for p, (ok, _) in zip(ports, results, strict=True) if ok]
    closed_ports = [p for p, (ok, _) in zip(ports, results, strict=True) if not ok]
    details = {"host": host, "ports": port_status, "open": open_ports, "closed": closed_ports}

    if closed_ports:
        return CheckResult(
            target=target.name, kind="port", status=Status.DOWN,
            message=f"Closed port(s): {', '.join(map(str, closed_ports))}", details=details,
        )
    return CheckResult(
        target=target.name, kind="port", status=Status.UP,
        message=f"All {len(open_ports)} port(s) open", details=details,
    )
