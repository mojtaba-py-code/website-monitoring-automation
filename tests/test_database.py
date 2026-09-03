"""Tests for the SQLite repository."""

from __future__ import annotations

from pathlib import Path

from webmon.database import Database, NullDatabase, open_database
from webmon.models import CheckResult, Status, TargetResult


def _result(ok: bool) -> TargetResult:
    status = Status.UP if ok else Status.DOWN
    return TargetResult.from_checks("site", "https://site.test",
                                    [CheckResult("site", "http", status, latency_ms=100.0)])


def test_record_and_availability(tmp_path: Path) -> None:
    db = Database(tmp_path / "h.db")
    try:
        for ok in (True, True, False, True):
            db.record_result(_result(ok))
        stats = db.availability("site", hours=24)
        assert stats["samples"] == 4
        assert stats["availability_pct"] == 75.0
        assert stats["failures"] == 1
        assert stats["avg_ms"] == 100.0
    finally:
        db.close()


def test_state_roundtrip(tmp_path: Path) -> None:
    db = Database(tmp_path / "h.db")
    try:
        assert db.get_state("x")["consecutive_failures"] == 0
        db.update_state("x", last_status="down", consecutive_failures=3, content_checksum="abc")
        state = db.get_state("x")
        assert state["last_status"] == "down"
        assert state["consecutive_failures"] == 3
        assert state["content_checksum"] == "abc"
    finally:
        db.close()


def test_events_and_alerts(tmp_path: Path) -> None:
    db = Database(tmp_path / "h.db")
    try:
        db.record_event("s", "up", "down", "http:down")
        db.record_alert("s", "critical", "s is DOWN", "detail", ["telegram"])
        assert db.recent_events()[0]["to_status"] == "down"
        assert db.recent_alerts()[0]["severity"] == "critical"
    finally:
        db.close()


def test_purge(tmp_path: Path) -> None:
    db = Database(tmp_path / "h.db")
    try:
        db.record_result(_result(True))
        assert db.purge(0) == 0  # retention 0 = keep forever
        removed = db.purge(-1) if False else db.purge(365)
        assert removed == 0  # nothing old enough
    finally:
        db.close()


def test_null_database() -> None:
    db = open_database(Path("unused.db"), enabled=False)
    assert isinstance(db, NullDatabase)
    db.record_result(_result(True))
    assert db.availability("x")["samples"] == 0
    assert db.recent_results() == []
    db.close()
