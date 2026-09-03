"""Tests for the alert decision engine (flap-suppression / recovery)."""

from __future__ import annotations

from webmon.alerting import AlertManager
from webmon.alerting.base import AlertSeverity
from webmon.config import AlertingConfig
from webmon.models import Status


def _manager(**kw: object) -> AlertManager:
    return AlertManager(AlertingConfig(enabled=True, **kw))  # type: ignore[arg-type]


def test_no_alert_below_threshold() -> None:
    mgr = _manager(failure_threshold=2)
    alert = mgr.decide(target="t", url="u", new_status=Status.DOWN, prev_status="up",
                       consecutive_failures=1, last_alert_ts=None)
    assert alert is None


def test_alert_at_threshold_is_critical() -> None:
    mgr = _manager(failure_threshold=2)
    alert = mgr.decide(target="t", url="u", new_status=Status.DOWN, prev_status="down",
                       consecutive_failures=2, last_alert_ts=None)
    assert alert is not None
    assert alert.severity == AlertSeverity.CRITICAL


def test_degraded_is_warning() -> None:
    mgr = _manager(failure_threshold=1)
    alert = mgr.decide(target="t", url="u", new_status=Status.DEGRADED, prev_status="up",
                       consecutive_failures=1, last_alert_ts=None)
    assert alert is not None
    assert alert.severity == AlertSeverity.WARNING


def test_recovery_alert() -> None:
    mgr = _manager(notify_on_recovery=True)
    alert = mgr.decide(target="t", url="u", new_status=Status.UP, prev_status="down",
                       consecutive_failures=0, last_alert_ts=None)
    assert alert is not None
    assert alert.severity == AlertSeverity.INFO
    assert "recovered" in alert.title


def test_no_recovery_when_already_up() -> None:
    mgr = _manager()
    alert = mgr.decide(target="t", url="u", new_status=Status.UP, prev_status="up",
                       consecutive_failures=0, last_alert_ts=None)
    assert alert is None


def test_renotify_suppression() -> None:
    mgr = _manager(failure_threshold=1, renotify_seconds=3600)
    from webmon.utils import iso_now

    alert = mgr.decide(target="t", url="u", new_status=Status.DOWN, prev_status="down",
                       consecutive_failures=5, last_alert_ts=iso_now())
    assert alert is None  # alerted recently, within renotify window


def test_disabled_manager_is_quiet() -> None:
    mgr = AlertManager(AlertingConfig(enabled=False))
    assert not mgr.enabled
    assert mgr.decide(target="t", url="u", new_status=Status.DOWN, prev_status="up",
                      consecutive_failures=99, last_alert_ts=None) is None
