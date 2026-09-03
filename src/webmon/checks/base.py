"""Shared plumbing for probes: effective settings, auth, and a safe HTTP client.

``CheckContext`` bundles everything a probe needs (the global settings and the
SSRF ``UrlGuard``) and derives per-target *effective* values (timeout, TLS
verification, headers, auth) so each probe stays small and declarative.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

from ..config import Settings, Target
from ..security import UrlGuard


@dataclass(slots=True)
class EffectiveSettings:
    timeout: float
    connect_timeout: float
    verify_ssl: bool
    follow_redirects: bool
    max_redirects: int
    max_response_bytes: int
    max_response_time_ms: int
    ssl_warning_days: int
    domain_warning_days: int
    retries: int
    retry_backoff: float
    user_agent: str
    dns_servers: list[str]


class CheckContext:
    """Per-run context handed to every probe."""

    def __init__(self, settings: Settings, guard: UrlGuard) -> None:
        self.settings = settings
        self.guard = guard

    def effective(self, target: Target) -> EffectiveSettings:
        """Merge global defaults with per-target overrides."""
        d = self.settings.defaults
        return EffectiveSettings(
            timeout=target.timeout_seconds if target.timeout_seconds is not None else d.timeout_seconds,
            connect_timeout=self.settings.performance.connect_timeout_seconds,
            verify_ssl=target.verify_ssl if target.verify_ssl is not None else d.verify_ssl,
            follow_redirects=(
                target.follow_redirects if target.follow_redirects is not None else d.follow_redirects
            ),
            max_redirects=d.max_redirects,
            max_response_bytes=d.max_response_bytes,
            max_response_time_ms=(
                target.max_response_time_ms
                if target.max_response_time_ms is not None
                else d.max_response_time_ms
            ),
            ssl_warning_days=(
                target.ssl_warning_days if target.ssl_warning_days is not None else d.ssl_warning_days
            ),
            domain_warning_days=d.domain_warning_days,
            retries=d.retries,
            retry_backoff=d.retry_backoff_seconds,
            user_agent=d.user_agent,
            dns_servers=list(d.dns_servers),
        )

    def build_headers(self, target: Target) -> dict[str, str]:
        """Compose request headers: User-Agent, custom headers, and auth."""
        headers: dict[str, str] = {"User-Agent": self.effective(target).user_agent}
        headers.update(target.headers)
        auth = target.auth
        if auth.type == "bearer" and auth.token:
            headers["Authorization"] = f"Bearer {auth.token}"
        elif auth.type == "basic" and auth.username:
            raw = f"{auth.username}:{auth.password}".encode()
            headers["Authorization"] = "Basic " + base64.b64encode(raw).decode("ascii")
        elif auth.type == "apikey" and auth.api_key:
            headers[auth.api_key_header] = auth.api_key
        return headers
