"""Tests for the e-mail alert channel's TLS behaviour.

The channel must never hand SMTP credentials to an unauthenticated or
unencrypted session: ``smtplib``'s default STARTTLS context verifies neither the
certificate chain nor the hostname, so the channel has to pass its own.
"""

from __future__ import annotations

import ssl
from typing import Any, ClassVar

import pytest

from webmon.alerting.base import Alert, AlertSeverity
from webmon.alerting.channels import EmailNotifier
from webmon.config import EmailChannel


def _alert() -> Alert:
    return Alert(target="t", severity=AlertSeverity.CRITICAL, title="down", message="body")


class _FakeSMTP:
    """Records how the channel drives smtplib."""

    instances: ClassVar[list[_FakeSMTP]] = []

    def __init__(self, host: str, port: int, timeout: float = 0.0, context: Any = None) -> None:
        self.host = host
        self.port = port
        self.implicit_context = context
        self.starttls_context: ssl.SSLContext | None = None
        self.logged_in = False
        self.sent = False
        _FakeSMTP.instances.append(self)

    def __enter__(self) -> _FakeSMTP:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def starttls(self, *, context: ssl.SSLContext | None = None) -> None:
        self.starttls_context = context

    def login(self, username: str, password: str) -> None:
        self.logged_in = True

    def sendmail(self, from_addr: str, to_addrs: list[str], msg: str) -> None:
        self.sent = True


@pytest.fixture(autouse=True)
def _reset() -> None:
    _FakeSMTP.instances.clear()


def _config(**kw: Any) -> EmailChannel:
    base: dict[str, Any] = {
        "enabled": True,
        "smtp_host": "smtp.example.test",
        "from_addr": "webmon@example.test",
        "to_addrs": ["ops@example.test"],
    }
    base.update(kw)
    return EmailChannel(**base)


def test_starttls_uses_a_verified_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("webmon.alerting.channels.smtplib.SMTP", _FakeSMTP)
    notifier = EmailNotifier(_config(use_tls=True, username="u", password="p"))

    assert notifier._send_blocking(_alert()) is True

    server = _FakeSMTP.instances[0]
    context = server.starttls_context
    assert context is not None, "STARTTLS must be given an explicit context"
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert server.logged_in and server.sent


def test_implicit_ssl_uses_smtp_ssl_with_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("webmon.alerting.channels.smtplib.SMTP_SSL", _FakeSMTP)
    notifier = EmailNotifier(_config(use_ssl=True, smtp_port=465, username="u", password="p"))

    assert notifier._send_blocking(_alert()) is True

    server = _FakeSMTP.instances[0]
    assert server.port == 465
    assert isinstance(server.implicit_context, ssl.SSLContext)
    assert server.implicit_context.check_hostname is True
    assert server.starttls_context is None, "implicit TLS must not also STARTTLS"


def test_credentials_are_never_sent_in_the_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("webmon.alerting.channels.smtplib.SMTP", _FakeSMTP)
    notifier = EmailNotifier(_config(use_tls=False, use_ssl=False, username="u", password="p"))

    assert notifier._send_blocking(_alert()) is False

    server = _FakeSMTP.instances[0]
    assert not server.logged_in
    assert not server.sent


def test_unauthenticated_relay_without_tls_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """No credentials at stake, so a plain local relay still works."""
    monkeypatch.setattr("webmon.alerting.channels.smtplib.SMTP", _FakeSMTP)
    notifier = EmailNotifier(_config(use_tls=False, use_ssl=False))

    assert notifier._send_blocking(_alert()) is True
    assert _FakeSMTP.instances[0].sent


def test_incomplete_config_is_a_no_op() -> None:
    assert EmailNotifier(EmailChannel(enabled=True))._send_blocking(_alert()) is False
