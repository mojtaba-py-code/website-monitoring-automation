"""TLS certificate probe: issuer, validity window and expiry countdown.

Fetches the peer certificate via a TLS handshake and parses it with
``cryptography``. Reports days-until-expiry and flags a WARNING when the cert
expires within the configured window, DOWN when it is expired/invalid or the
handshake fails.
"""

from __future__ import annotations

import asyncio
import socket
import ssl
from datetime import timezone
from urllib.parse import urlparse

from cryptography import x509
from cryptography.hazmat.backends import default_backend

from ..config import Target
from ..models import CheckResult, Status
from ..utils import utcnow
from .base import CheckContext


def _fetch_certificate(host: str, port: int, timeout: float) -> x509.Certificate:
    """Blocking TLS handshake returning the parsed leaf certificate."""
    context = ssl.create_default_context()
    # create_default_context() already floors at TLS 1.2 on supported Pythons;
    # stating it makes the guarantee explicit and immune to a future default
    # change, and documents that a peer stuck on TLS 1.0/1.1 is reported as an
    # error rather than quietly inspected.
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    with (
        socket.create_connection((host, port), timeout=timeout) as sock,
        context.wrap_socket(sock, server_hostname=host) as tls,
    ):
        der = tls.getpeercert(binary_form=True)
    if not der:  # pragma: no cover - defensive
        raise ssl.SSLError("No certificate presented by peer")
    return x509.load_der_x509_certificate(der, default_backend())


def _name_str(name: x509.Name) -> str:
    try:
        return name.rfc4514_string()
    except Exception:  # pragma: no cover - defensive
        return str(name)


async def check_ssl(target: Target, ctx: CheckContext) -> CheckResult:
    eff = ctx.effective(target)
    parsed = urlparse(target.url)
    if parsed.scheme != "https":
        return CheckResult(
            target=target.name, kind="ssl", status=Status.UNKNOWN,
            message="Not an HTTPS URL; SSL check skipped",
        )
    host = parsed.hostname or ""
    port = parsed.port or 443

    # Validate the host against SSRF policy before connecting.
    try:
        await asyncio.to_thread(ctx.guard.validate, target.url)
    except Exception as exc:  # SecurityError
        return CheckResult(target=target.name, kind="ssl", status=Status.DOWN, message=str(exc))

    try:
        cert = await asyncio.to_thread(_fetch_certificate, host, port, eff.timeout)
    except (ssl.SSLError, ssl.CertificateError) as exc:
        return CheckResult(
            target=target.name, kind="ssl", status=Status.DOWN,
            message=f"TLS error: {exc}",
        )
    except (TimeoutError, OSError) as exc:
        return CheckResult(
            target=target.name, kind="ssl", status=Status.DOWN,
            message=f"Connection failed: {exc}",
        )

    not_after = cert.not_valid_after_utc
    not_before = cert.not_valid_before_utc
    now = utcnow()
    days_left = (not_after - now).total_seconds() / 86400.0

    details = {
        "issuer": _name_str(cert.issuer),
        "subject": _name_str(cert.subject),
        "not_before": not_before.astimezone(timezone.utc).isoformat(),
        "not_after": not_after.astimezone(timezone.utc).isoformat(),
        "days_until_expiry": round(days_left, 1),
        "serial": format(cert.serial_number, "x"),
    }

    if now < not_before:
        return CheckResult(target=target.name, kind="ssl", status=Status.DOWN,
                           message="Certificate not yet valid", details=details)
    if days_left <= 0:
        return CheckResult(target=target.name, kind="ssl", status=Status.DOWN,
                           message="Certificate expired", details=details)
    if days_left <= eff.ssl_warning_days:
        return CheckResult(
            target=target.name, kind="ssl", status=Status.WARNING,
            message=f"Certificate expires in {days_left:.0f} day(s)", details=details,
        )
    return CheckResult(
        target=target.name, kind="ssl", status=Status.UP,
        message=f"Valid for {days_left:.0f} more day(s)", details=details,
    )
