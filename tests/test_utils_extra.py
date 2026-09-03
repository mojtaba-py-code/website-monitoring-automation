"""Coverage for utility helpers, scheduler snippets, dispatch and DNS internals."""

from __future__ import annotations

import pytest

from webmon.alerting import AlertManager
from webmon.alerting.base import Alert, AlertSeverity
from webmon.config import AlertingConfig
from webmon.scheduler import cron_line, windows_task_command
from webmon.utils import clamp, human_duration, human_size, percentile, retry_async


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0.25, "250 ms"), (5, "5s"), (65, "1m 05s"), (3665, "1h 01m"), (90000, "1d 01h")],
)
def test_human_duration(seconds: float, expected: str) -> None:
    assert human_duration(seconds) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, "0 B"), (2048, "2.00 KiB"), (1048576, "1.00 MiB")],
)
def test_human_size(value: int, expected: str) -> None:
    assert human_size(value) == expected


def test_clamp() -> None:
    assert clamp(5, 0, 10) == 5
    assert clamp(-1, 0, 10) == 0
    assert clamp(99, 0, 10) == 10


def test_percentile() -> None:
    data = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert percentile(data, 0) == 10.0
    assert percentile(data, 100) == 50.0
    assert percentile([], 95) == 0.0


async def test_retry_async_succeeds_after_failures() -> None:
    calls = {"n": 0}

    async def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise OSError("transient")
        return "ok"

    assert await retry_async(flaky, attempts=3, backoff=0.0) == "ok"
    assert calls["n"] == 3


async def test_retry_async_reraises() -> None:
    async def always_fail() -> None:
        raise ValueError("nope")

    with pytest.raises(ValueError, match="nope"):
        await retry_async(always_fail, attempts=1, backoff=0.0, exceptions=(ValueError,))


def test_cron_line() -> None:
    assert cron_line("webmon check", 5) == "*/5 * * * * webmon check"
    assert cron_line("webmon check", 120).startswith("0 */2")


def test_windows_task_command() -> None:
    cmd = windows_task_command("Webmon", "webmon check", 10)
    assert "schtasks /Create" in cmd
    assert "/MO 10" in cmd


async def test_dispatch_no_channels_returns_empty() -> None:
    mgr = AlertManager(AlertingConfig(enabled=True))  # enabled but no channels configured
    result = await mgr.dispatch(Alert("t", AlertSeverity.CRITICAL, "x", "y"))
    assert result == []


def test_dns_resolve_records_with_fake_resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    from webmon.checks import dns_check

    class FakeRecord:
        def __init__(self, text: str) -> None:
            self._t = text

        def to_text(self) -> str:
            return self._t

    class FakeResolver:
        def __init__(self, *a: object, **k: object) -> None:
            self.nameservers: list[str] = []
            self.lifetime = 0.0
            self.timeout = 0.0

        def resolve(self, host: str, rtype: str) -> list[FakeRecord]:
            return [FakeRecord("93.184.216.34")]

    monkeypatch.setattr(dns_check.dns.resolver, "Resolver", FakeResolver)
    records = dns_check._resolve_records("example.com", ["A"], [], 5.0)
    assert records == {"A": ["93.184.216.34"]}
