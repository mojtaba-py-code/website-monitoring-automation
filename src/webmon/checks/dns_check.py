"""DNS resolution probe.

Resolves the configured record types for a target's host (optionally against
specific DNS servers) and returns the records found. Change detection across
runs is handled by the monitor/database layer, which compares the returned
records against the previously stored set.
"""

from __future__ import annotations

import asyncio
from urllib.parse import urlparse

import dns.resolver

from ..config import Target
from ..models import CheckResult, Status
from .base import CheckContext


def _resolve_records(host: str, record_types: list[str], servers: list[str], timeout: float) -> dict[str, list[str]]:
    resolver = dns.resolver.Resolver(configure=not servers)
    if servers:
        resolver.nameservers = servers
    resolver.lifetime = timeout
    resolver.timeout = timeout
    records: dict[str, list[str]] = {}
    for rtype in record_types:
        try:
            answer = resolver.resolve(host, rtype)
            records[rtype] = sorted(r.to_text() for r in answer)
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            records[rtype] = []
        except (dns.exception.DNSException, OSError):
            records[rtype] = []
    return records


async def check_dns(target: Target, ctx: CheckContext) -> CheckResult:
    eff = ctx.effective(target)
    host = urlparse(target.url).hostname or ""
    if not host:
        return CheckResult(target=target.name, kind="dns", status=Status.DOWN, message="No host in URL")

    record_types = target.dns_record_types or ["A"]
    try:
        records = await asyncio.to_thread(
            _resolve_records, host, record_types, eff.dns_servers, eff.timeout
        )
    except Exception as exc:  # pragma: no cover - defensive
        return CheckResult(target=target.name, kind="dns", status=Status.DOWN, message=f"DNS error: {exc}")

    total = sum(len(v) for v in records.values())
    # A "fingerprint" the monitor stores to detect record changes over time.
    fingerprint = ";".join(f"{k}={','.join(v)}" for k, v in sorted(records.items()))
    details = {"records": records, "fingerprint": fingerprint, "host": host}

    if total == 0:
        return CheckResult(
            target=target.name, kind="dns", status=Status.DOWN,
            message=f"No DNS records resolved for {host}", details=details,
        )
    return CheckResult(
        target=target.name, kind="dns", status=Status.UP,
        message=f"Resolved {total} record(s) across {len(record_types)} type(s)", details=details,
    )
