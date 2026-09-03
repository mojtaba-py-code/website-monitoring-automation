"""Tests for the SSRF URL guard and secret redaction."""

from __future__ import annotations

import pytest

from webmon.config import SecurityConfig
from webmon.security import SecurityError, UrlGuard, redact, redact_headers, redact_url


def _guard(**kw: object) -> UrlGuard:
    return UrlGuard(SecurityConfig(**kw))  # type: ignore[arg-type]


def test_scheme_allowlist() -> None:
    with pytest.raises(SecurityError, match="Scheme not allowed"):
        _guard().validate("ftp://example.com", resolve=False)


def test_blocklist_host() -> None:
    guard = _guard(blocklist_hosts=["169.254.169.254"])
    with pytest.raises(SecurityError, match="block-listed"):
        guard.validate("http://169.254.169.254/latest/meta-data", resolve=False)


def test_private_ip_blocked_by_default() -> None:
    guard = _guard(block_private_networks=True)
    for host in ("http://127.0.0.1/", "http://10.0.0.5/", "http://192.168.1.1/", "http://[::1]/"):
        with pytest.raises(SecurityError, match="non-public"):
            guard.validate(host)


def test_private_ip_allowed_when_disabled() -> None:
    guard = _guard(block_private_networks=False)
    result = guard.validate("http://127.0.0.1:8080/health")
    assert result.host == "127.0.0.1"
    assert result.port == 8080


def test_allowlist_overrides_private_block() -> None:
    guard = _guard(block_private_networks=True, allowlist_hosts=["127.0.0.1"])
    assert guard.validate("http://127.0.0.1/").host == "127.0.0.1"


def test_public_ip_allowed() -> None:
    guard = _guard(block_private_networks=True)
    assert guard.validate("https://1.1.1.1/").port == 443


def test_ipv4_mapped_ipv6_is_blocked() -> None:
    # A mapped loopback/metadata address must not slip past the guard.
    assert UrlGuard._ip_is_forbidden("::ffff:127.0.0.1")
    assert UrlGuard._ip_is_forbidden("::ffff:169.254.169.254")
    assert not UrlGuard._ip_is_forbidden("::ffff:1.1.1.1")


def test_malformed_url() -> None:
    with pytest.raises(SecurityError):
        _guard().validate("http://", resolve=False)


@pytest.mark.parametrize(
    ("raw", "must_not_contain"),
    [
        ("Authorization: Bearer abcdef123456", "abcdef123456"),
        ("https://x.com/?token=SUPERSECRET1", "SUPERSECRET1"),
        ("https://user:hunter2@host/path", "hunter2"),
        ("api_key=ABCDEF123", "ABCDEF123"),
    ],
)
def test_redact_masks_secrets(raw: str, must_not_contain: str) -> None:
    assert must_not_contain not in redact(raw)
    assert "***" in redact(raw)


def test_redact_url_strips_userinfo_and_query() -> None:
    out = redact_url("https://user:pass@host/path?token=abc&x=1")
    assert "pass" not in out
    assert "abc" not in out
    assert "host/path" in out


def test_redact_headers() -> None:
    masked = redact_headers({"Authorization": "Bearer x", "Cookie": "s=1", "Accept": "json"})
    assert masked["Authorization"] == "***"
    assert masked["Cookie"] == "***"
    assert masked["Accept"] == "json"


def test_blocklist_matches_resolved_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    """A hostname pointing at a block-listed IP must be refused.

    The name itself is innocuous, so only the post-resolution check can catch it
    (the classic `*.nip.io`-style wildcard-DNS route to the metadata endpoint).
    """
    monkeypatch.setattr(UrlGuard, "_resolve", lambda self, host: ["169.254.169.254"])
    guard = _guard(block_private_networks=False, blocklist_hosts=["169.254.169.254"])
    with pytest.raises(SecurityError, match="block-listed address"):
        guard.validate("http://metadata.example.test/latest/meta-data")


def test_resolved_ip_blocklist_allows_clean_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(UrlGuard, "_resolve", lambda self, host: ["93.184.216.34"])
    guard = _guard(block_private_networks=True, blocklist_hosts=["169.254.169.254"])
    assert guard.validate("https://example.test/").resolved_ips == ["93.184.216.34"]
