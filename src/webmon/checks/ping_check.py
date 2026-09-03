"""ICMP ping probe (cross-platform, via the system ``ping`` command).

Raw ICMP sockets require elevated privileges, so this shells out to the OS
``ping`` utility with a fixed, non-shell argument vector (no injection surface)
and parses the packet-loss / average-latency summary. Reports DEGRADED on
partial loss and DOWN on total loss or an unreachable host.
"""

from __future__ import annotations

import asyncio
import os
import re
from urllib.parse import urlparse

from ..config import Target
from ..models import CheckResult, Status
from .base import CheckContext

_LOSS_RE = re.compile(r"(\d+(?:\.\d+)?)%\s*(?:packet\s*)?loss", re.IGNORECASE)
_AVG_RE = re.compile(r"(?:Average|avg|rtt[^=]*=[^/]*/)\s*=?\s*([\d.]+)", re.IGNORECASE)


def _build_command(host: str, count: int, timeout: float) -> list[str]:
    if os.name == "nt":
        # -n count, -w timeout(ms)
        return ["ping", "-n", str(count), "-w", str(int(timeout * 1000)), host]
    # -c count, -W timeout(seconds, integer)
    return ["ping", "-c", str(count), "-W", str(max(1, int(timeout))), host]


def _parse(output: str) -> tuple[float, float | None]:
    loss_match = _LOSS_RE.search(output)
    loss = float(loss_match.group(1)) if loss_match else 100.0
    avg_match = _AVG_RE.search(output)
    avg = float(avg_match.group(1)) if avg_match else None
    return loss, avg


def _is_safe_host(host: str) -> bool:
    """Reject hosts that could be interpreted as command-line options or are
    otherwise malformed, defending the argv against option injection."""
    if not host or host.startswith("-") or any(c.isspace() for c in host):
        return False
    return all(c.isalnum() or c in ".:-[]" for c in host)


async def check_ping(target: Target, ctx: CheckContext, *, count: int = 4) -> CheckResult:
    eff = ctx.effective(target)
    host = urlparse(target.url).hostname or target.url

    # Apply the SSRF policy (blocks private hosts unless allow-listed) and refuse
    # hostnames that could inject ping options.
    try:
        await asyncio.to_thread(ctx.guard.validate, target.url)
    except Exception as exc:  # SecurityError
        return CheckResult(target=target.name, kind="ping", status=Status.DOWN, message=str(exc))
    if not _is_safe_host(host):
        return CheckResult(target=target.name, kind="ping", status=Status.DOWN,
                           message=f"Unsafe host for ping: {host!r}")

    command = _build_command(host, count, eff.timeout)
    try:
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=eff.timeout * count + 5)
    except (TimeoutError, OSError, ValueError) as exc:
        return CheckResult(target=target.name, kind="ping", status=Status.DOWN, message=f"Ping failed: {exc}")

    output = stdout.decode("utf-8", errors="replace") if stdout else ""
    loss, avg = _parse(output)
    details = {"host": host, "packet_loss_pct": loss, "avg_latency_ms": avg}

    if loss >= 100.0:
        return CheckResult(target=target.name, kind="ping", status=Status.DOWN,
                           message=f"100% packet loss to {host}", details=details)
    if loss > 0.0:
        return CheckResult(target=target.name, kind="ping", status=Status.DEGRADED,
                           message=f"{loss:.0f}% packet loss to {host}", details=details)
    return CheckResult(
        target=target.name, kind="ping", status=Status.UP,
        message=f"0% loss, avg {avg:.1f}ms" if avg is not None else "Reachable", details=details,
    )
