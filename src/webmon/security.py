"""Security guardrails for outbound requests and log hygiene.

Two concerns live here:

1. **SSRF defence** (:class:`UrlGuard`) — before any request is made, the URL is
   validated: scheme allow-list, host block/allow-lists, and (optionally) a
   check that the resolved IP addresses are not private / loopback / link-local
   / reserved. Redirects are re-validated hop-by-hop by the HTTP check so an
   open redirect cannot bounce a probe onto an internal service (e.g. the cloud
   metadata endpoint ``169.254.169.254``).

2. **Secret redaction** (:func:`redact`, :func:`redact_headers`) — credentials
   must never reach a log file. These helpers mask tokens, passwords, API keys,
   URL user-info and sensitive query parameters before anything is logged.

Residual risk & threat model
----------------------------
The guard resolves and checks the target's IPs, but the HTTP client re-resolves
the hostname at connect time, so a hostile low-TTL domain could in theory rebind
to a private address between the check and the connection (DNS rebinding). In
this application targets come from the operator's own trusted config file (not
untrusted runtime input), which makes this impractical; the private-network
block and the ``blocklist_hosts`` default (cloud metadata IP) are the primary
defences. Keep ``block_private_networks: true`` in production.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

from .config import SecurityConfig


class SecurityError(Exception):
    """Raised when a URL/request violates a security guardrail."""


# --------------------------------------------------------------------------- #
# Secret redaction
# --------------------------------------------------------------------------- #
_SENSITIVE_QUERY_KEYS = ("token", "apikey", "api_key", "key", "secret", "password", "access_token")
_REDACTIONS = (
    # Bearer / token style secrets.
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{6,}"),
    # key=value secrets in query strings or bodies.
    re.compile(r"(?i)\b(" + "|".join(_SENSITIVE_QUERY_KEYS) + r")=([^&\s\"']{3,})"),
    # user:pass@ in URLs.
    re.compile(r"(?i)(://)([^:/@\s]+):([^@/\s]+)@"),
)
_MASK = "***"


def redact(value: str) -> str:
    """Return ``value`` with common secret patterns masked.

    Idempotent and safe to call on any string before logging.
    """
    if not value:
        return value
    text = _REDACTIONS[0].sub(rf"\1{_MASK}", value)
    text = _REDACTIONS[1].sub(rf"\1={_MASK}", text)
    text = _REDACTIONS[2].sub(rf"\1\2:{_MASK}@", text)
    return text


def redact_url(url: str) -> str:
    """Strip user-info and mask sensitive query params from a URL for logging."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return _MASK
    netloc = parsed.hostname or ""
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    query = parsed.query
    for key in _SENSITIVE_QUERY_KEYS:
        query = re.sub(rf"(?i)\b{key}=[^&]*", f"{key}={_MASK}", query)
    return urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, query, ""))


_SENSITIVE_HEADERS = frozenset(
    {"authorization", "cookie", "set-cookie", "x-api-key", "proxy-authorization"}
)
# Substrings that mark a header as credential-bearing. A target's API-key header
# name is operator-configurable (``auth.api_key_header``), so an exact-match list
# alone would silently log a key sent under a custom name such as
# ``X-Custom-Auth``. Over-masking a header in a log is harmless; under-masking
# one leaks a secret, so the heuristic errs toward masking.
_SENSITIVE_HEADER_PARTS = (
    "auth",
    "token",
    "secret",
    "password",
    "credential",
    "cookie",
    "key",
)


def _is_sensitive_header(name: str) -> bool:
    lowered = name.lower()
    return lowered in _SENSITIVE_HEADERS or any(part in lowered for part in _SENSITIVE_HEADER_PARTS)


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    """Return a copy of ``headers`` with credential-bearing values masked."""
    return {k: (_MASK if _is_sensitive_header(k) else v) for k, v in headers.items()}


# --------------------------------------------------------------------------- #
# SSRF / URL guard
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class ValidatedURL:
    url: str
    scheme: str
    host: str
    port: int
    resolved_ips: list[str]


class UrlGuard:
    """Validates URLs against SSRF and scheme/host policy before a request."""

    def __init__(self, config: SecurityConfig) -> None:
        self._config = config
        self._allowed_schemes = {s.lower() for s in config.allowed_schemes}
        self._allowlist = {h.lower() for h in config.allowlist_hosts}
        self._blocklist = {h.lower() for h in config.blocklist_hosts}

    @staticmethod
    def _default_port(scheme: str) -> int:
        return {"http": 80, "https": 443}.get(scheme, 0)

    @staticmethod
    def _ip_is_forbidden(ip: str) -> bool:
        try:
            addr: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address(ip)
        except ValueError:  # pragma: no cover - defensive
            return True
        # Unwrap IPv4-mapped IPv6 (e.g. ::ffff:169.254.169.254) so a mapped
        # metadata/loopback address cannot slip past the checks on older CPython.
        if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
            addr = addr.ipv4_mapped
        return (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
            or addr.is_unspecified
        )

    def _resolve(self, host: str) -> list[str]:
        """Resolve a hostname to its IP addresses (blocking; call via a thread)."""
        try:
            infos = socket.getaddrinfo(host, None)
        except OSError as exc:
            raise SecurityError(f"DNS resolution failed for {host}: {exc}") from exc
        ips = sorted({str(info[4][0]) for info in infos})
        if not ips:
            raise SecurityError(f"No addresses resolved for {host}")
        return ips

    def validate(self, url: str, *, resolve: bool = True) -> ValidatedURL:
        """Validate ``url`` and return a :class:`ValidatedURL`.

        Raises :class:`SecurityError` on any policy violation. When ``resolve``
        is True the host is DNS-resolved and each IP checked against the
        private/reserved policy (this is a blocking call).
        """
        try:
            parsed = urlparse(url)
        except ValueError as exc:
            raise SecurityError(f"Malformed URL: {redact_url(url)} ({exc})") from exc

        scheme = (parsed.scheme or "").lower()
        if scheme not in self._allowed_schemes:
            raise SecurityError(f"Scheme not allowed: {scheme or '(none)'}")
        host = parsed.hostname
        if not host:
            raise SecurityError(f"URL has no host: {redact_url(url)}")
        host_l = host.lower()
        if host_l in self._blocklist:
            raise SecurityError(f"Host is block-listed: {host}")

        port = parsed.port or self._default_port(scheme)

        resolved: list[str] = []
        if resolve:
            # A literal IP host is checked directly; a name is resolved first.
            try:
                ipaddress.ip_address(host)
                resolved = [host]
            except ValueError:
                resolved = self._resolve(host)

            # The block-list is enforced against the *resolved* addresses too, so
            # a hostname that merely points at a block-listed IP (e.g. one of the
            # public `*.nip.io`-style wildcard resolvers aimed at 169.254.169.254)
            # cannot slip past the name-only check above.
            for ip in resolved:
                if ip.lower() in self._blocklist:
                    raise SecurityError(f"Host {host} resolves to block-listed address {ip}")

            if self._config.block_private_networks and host_l not in self._allowlist:
                for ip in resolved:
                    if self._ip_is_forbidden(ip):
                        raise SecurityError(
                            f"Refusing request to non-public address {ip} (host {host})"
                        )
        return ValidatedURL(url=url, scheme=scheme, host=host, port=port, resolved_ips=resolved)

    def validate_redirect(self, url: str, *, resolve: bool = True) -> ValidatedURL:
        """Validate a redirect target with the same policy as the initial URL."""
        if not self._config.validate_redirects:
            return self.validate(url, resolve=False)
        return self.validate(url, resolve=resolve)
