"""SSRF-safe HTTP fetching shared by the http / api / content probes.

``safe_fetch`` performs a single request with redirects followed **manually** so
that every hop is re-validated by the :class:`~webmon.security.UrlGuard`. This
closes the classic open-redirect -> SSRF path (e.g. a site 302-ing a probe to
``http://169.254.169.254/``). The response body is read with a hard size cap to
bound memory use.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import httpx

from ..logger import get_logger
from ..security import SecurityError, redact_headers, redact_url
from .base import CheckContext, EffectiveSettings

logger = get_logger("checks.http")


@dataclass(slots=True)
class FetchResult:
    ok: bool
    status_code: int | None = None
    latency_ms: float | None = None
    body: bytes = b""
    truncated: bool = False
    final_url: str = ""
    redirects: int = 0
    headers: dict[str, str] = field(default_factory=dict)
    error: str | None = None


async def _read_capped(response: httpx.Response, cap: int) -> tuple[bytes, bool]:
    """Read up to ``cap`` bytes from a streaming response."""
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        chunks.append(chunk)
        total += len(chunk)
        if total >= cap:
            return b"".join(chunks)[:cap], True
    return b"".join(chunks), False


async def safe_fetch(
    url: str,
    ctx: CheckContext,
    eff: EffectiveSettings,
    headers: dict[str, str],
    *,
    method: str = "GET",
) -> FetchResult:
    """Fetch ``url`` with per-hop SSRF validation and a response-size cap."""
    try:
        await asyncio.to_thread(ctx.guard.validate, url)
    except SecurityError as exc:
        return FetchResult(ok=False, error=str(exc))

    # Debug logging is secret-safe: the URL and headers are redacted.
    logger.debug("fetch %s %s headers=%s", method, redact_url(url), redact_headers(headers))

    timeout = httpx.Timeout(eff.timeout, connect=eff.connect_timeout)
    limits = httpx.Limits(max_keepalive_connections=10, max_connections=20)
    started = time.perf_counter()
    current = url
    origin_host = urlparse(url).hostname
    hop_headers = dict(headers)
    redirects = 0
    try:
        async with httpx.AsyncClient(
            verify=eff.verify_ssl, follow_redirects=False, timeout=timeout, limits=limits
        ) as client:
            while True:
                response = await client.request(method, current, headers=hop_headers)
                if eff.follow_redirects and response.is_redirect and redirects < eff.max_redirects:
                    location = response.headers.get("location", "")
                    await response.aclose()
                    if not location:
                        break
                    current = urljoin(current, location)
                    # Re-validate every redirect hop (anti-SSRF).
                    try:
                        await asyncio.to_thread(ctx.guard.validate_redirect, current)
                    except SecurityError as exc:
                        return FetchResult(ok=False, error=f"Blocked redirect: {exc}", redirects=redirects)
                    # Never carry credentials to a different host on redirect.
                    if urlparse(current).hostname != origin_host:
                        hop_headers.pop("Authorization", None)
                        hop_headers.pop("Cookie", None)
                    redirects += 1
                    continue
                body, truncated = await _read_capped(response, eff.max_response_bytes)
                latency = (time.perf_counter() - started) * 1000.0
                return FetchResult(
                    ok=True,
                    status_code=response.status_code,
                    latency_ms=round(latency, 2),
                    body=body,
                    truncated=truncated,
                    final_url=str(response.url),
                    redirects=redirects,
                    headers={k.lower(): v for k, v in response.headers.items()},
                )
    except httpx.TimeoutException:
        return FetchResult(ok=False, error="Request timed out", redirects=redirects)
    except (httpx.HTTPError, OSError) as exc:
        return FetchResult(ok=False, error=f"{type(exc).__name__}: {exc}", redirects=redirects)
    return FetchResult(ok=False, error="Too many redirects", redirects=redirects)
