"""Tests for the SSL / DNS / port / ping probes.

SSL uses an in-memory self-signed certificate (no real handshake); DNS is
monkeypatched; port runs against a real local asyncio server; ping is tested via
its pure parsing helpers plus a loopback smoke test.
"""

from __future__ import annotations

import asyncio
import datetime as dt

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from webmon.checks import dns_check, ssl_check
from webmon.checks.base import CheckContext
from webmon.checks.ping_check import _build_command, _is_safe_host, _parse, check_ping
from webmon.checks.port_check import check_port
from webmon.config import Target
from webmon.models import Status


def _make_cert(days: int) -> x509.Certificate:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test.local")])
    now = dt.datetime.now(dt.timezone.utc)
    return (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=days))
        .sign(key, hashes.SHA256())
    )


def _https_target() -> Target:
    return Target(name="t", url="https://127.0.0.1/", checks=["ssl"])  # type: ignore[arg-type]


async def test_ssl_valid(ctx: CheckContext, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ssl_check, "_fetch_certificate", lambda *a: _make_cert(60))
    result = await ssl_check.check_ssl(_https_target(), ctx)
    assert result.status == Status.UP
    assert result.details["days_until_expiry"] > 21


async def test_ssl_expiring_soon(ctx: CheckContext, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ssl_check, "_fetch_certificate", lambda *a: _make_cert(10))
    result = await ssl_check.check_ssl(_https_target(), ctx)
    assert result.status == Status.WARNING


async def test_ssl_expired(ctx: CheckContext, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ssl_check, "_fetch_certificate", lambda *a: _make_cert(-1))
    result = await ssl_check.check_ssl(_https_target(), ctx)
    assert result.status == Status.DOWN
    assert "expired" in result.message.lower()


async def test_ssl_skips_http(ctx: CheckContext) -> None:
    target = Target(name="t", url="http://127.0.0.1/", checks=["ssl"])  # type: ignore[arg-type]
    result = await ssl_check.check_ssl(target, ctx)
    assert result.status == Status.UNKNOWN


async def test_dns_resolves(ctx: CheckContext, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dns_check, "_resolve_records", lambda *a: {"A": ["93.184.216.34"]})
    target = Target(name="t", url="https://example.test/", checks=["dns"], dns_record_types=["A"])  # type: ignore[arg-type]
    result = await dns_check.check_dns(target, ctx)
    assert result.status == Status.UP
    assert "A=93.184.216.34" in result.details["fingerprint"]


async def test_dns_nxdomain(ctx: CheckContext, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dns_check, "_resolve_records", lambda *a: {"A": []})
    target = Target(name="t", url="https://nope.test/", checks=["dns"])  # type: ignore[arg-type]
    result = await dns_check.check_dns(target, ctx)
    assert result.status == Status.DOWN


async def test_port_open(ctx: CheckContext) -> None:
    server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        target = Target(name="t", url="http://127.0.0.1/", checks=["port"], ports=[port])  # type: ignore[arg-type]
        result = await check_port(target, ctx)
        assert result.status == Status.UP
        assert port in result.details["open"]
    finally:
        server.close()
        await server.wait_closed()


async def test_port_closed(ctx: CheckContext) -> None:
    target = Target(name="t", url="http://127.0.0.1/", checks=["port"], ports=[59999])  # type: ignore[arg-type]
    result = await check_port(target, ctx)
    assert result.status == Status.DOWN
    assert 59999 in result.details["closed"]


def test_ping_build_command_windows_and_unix() -> None:
    import os

    cmd = _build_command("example.com", 4, 5.0)
    assert cmd[0] == "ping"
    if os.name == "nt":
        assert "-n" in cmd
    else:
        assert "-c" in cmd


def test_ping_parse() -> None:
    unix = "4 packets transmitted, 4 received, 0% packet loss\nrtt min/avg/max = 1.0/2.5/3.0 ms"
    loss, avg = _parse(unix)
    assert loss == 0.0
    assert avg == 2.5
    loss2, _ = _parse("100% packet loss")
    assert loss2 == 100.0


def test_ping_rejects_unsafe_hosts() -> None:
    assert _is_safe_host("example.com")
    assert _is_safe_host("127.0.0.1")
    assert not _is_safe_host("-oL/tmp/x")   # option-injection attempt
    assert not _is_safe_host("bad host")
    assert not _is_safe_host("")


async def test_ping_loopback_returns_result(ctx: CheckContext) -> None:
    target = Target(name="t", url="http://127.0.0.1/", checks=["ping"])  # type: ignore[arg-type]
    result = await check_ping(target, ctx, count=1)
    assert result.kind == "ping"
    assert isinstance(result.status, Status)
