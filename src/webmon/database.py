"""SQLite persistence (repository pattern) for monitoring history & analytics.

Stores every check result, per-cycle target results, up/down state-change events,
raised alerts, and a small per-target ``state`` row used for flap-suppression and
change detection (DNS fingerprint, content checksum). A :class:`NullDatabase`
stand-in keeps callers branch-free when persistence is disabled.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol

from .models import CheckResult, TargetResult
from .utils import iso_now, utcnow

_SCHEMA = """
CREATE TABLE IF NOT EXISTS checks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    target     TEXT NOT NULL,
    kind       TEXT NOT NULL,
    status     TEXT NOT NULL,
    ok         INTEGER NOT NULL,
    latency_ms REAL,
    message    TEXT,
    details    TEXT,
    ts         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS results (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    target           TEXT NOT NULL,
    url              TEXT NOT NULL,
    status           TEXT NOT NULL,
    ok               INTEGER NOT NULL,
    response_time_ms REAL,
    ts               TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    target      TEXT NOT NULL,
    from_status TEXT,
    to_status   TEXT NOT NULL,
    message     TEXT,
    ts          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    target   TEXT NOT NULL,
    severity TEXT NOT NULL,
    title    TEXT NOT NULL,
    message  TEXT NOT NULL,
    channels TEXT,
    ts       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS state (
    target                 TEXT PRIMARY KEY,
    last_status            TEXT,
    last_change_ts         TEXT,
    consecutive_failures   INTEGER NOT NULL DEFAULT 0,
    last_alert_ts          TEXT,
    dns_fingerprint        TEXT,
    content_checksum       TEXT
);

CREATE INDEX IF NOT EXISTS idx_checks_target_ts ON checks(target, ts);
CREATE INDEX IF NOT EXISTS idx_results_target_ts ON results(target, ts);
CREATE INDEX IF NOT EXISTS idx_events_target_ts ON events(target, ts);
"""

# SQLite cannot parameterise an identifier, so the few queries that interpolate a
# table name check it against this set first. Every value is a literal from this
# module -- the guard exists so that stays true if a caller is ever added.
_HISTORY_TABLES = frozenset({"checks", "results", "events", "alerts"})


def _safe_table(name: str) -> str:
    """Return ``name`` if it is a known history table, else raise."""
    if name not in _HISTORY_TABLES:
        raise ValueError(f"Unknown table: {name!r}")
    return name


class DatabaseLike(Protocol):
    def record_check(self, result: CheckResult) -> None: ...
    def record_result(self, result: TargetResult) -> None: ...
    def record_event(self, target: str, from_status: str | None, to_status: str, message: str) -> None: ...
    def record_alert(self, target: str, severity: str, title: str, message: str, channels: list[str]) -> None: ...
    def get_state(self, target: str) -> dict[str, Any]: ...
    def update_state(self, target: str, **fields: Any) -> None: ...
    def availability(self, target: str, *, hours: int = 24) -> dict[str, Any]: ...
    def recent_results(self, *, limit: int = 50) -> list[dict[str, Any]]: ...
    def recent_events(self, *, limit: int = 50) -> list[dict[str, Any]]: ...
    def recent_alerts(self, *, limit: int = 50) -> list[dict[str, Any]]: ...
    def latency_series(self, target: str, *, hours: int = 24, limit: int = 200) -> list[dict[str, Any]]: ...
    def purge(self, retention_days: int) -> int: ...
    def close(self) -> None: ...


class Database:
    """Concrete SQLite-backed repository."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    @contextmanager
    def _cursor(self) -> Iterator[sqlite3.Cursor]:
        cur = self._conn.cursor()
        try:
            yield cur
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        finally:
            cur.close()

    # -- writes ------------------------------------------------------------ #
    def record_check(self, result: CheckResult) -> None:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO checks (target, kind, status, ok, latency_ms, message, details, ts)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    result.target, result.kind, result.status.value, int(result.ok),
                    result.latency_ms, result.message, json.dumps(result.details, default=str),
                    result.timestamp,
                ),
            )

    def record_result(self, result: TargetResult) -> None:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO results (target, url, status, ok, response_time_ms, ts)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (result.target, result.url, result.status.value, int(result.ok),
                 result.response_time_ms, result.timestamp),
            )

    def record_event(self, target: str, from_status: str | None, to_status: str, message: str) -> None:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO events (target, from_status, to_status, message, ts) VALUES (?, ?, ?, ?, ?)",
                (target, from_status, to_status, message, iso_now()),
            )

    def record_alert(self, target: str, severity: str, title: str, message: str, channels: list[str]) -> None:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO alerts (target, severity, title, message, channels, ts) VALUES (?, ?, ?, ?, ?, ?)",
                (target, severity, title, message, json.dumps(channels), iso_now()),
            )

    def get_state(self, target: str) -> dict[str, Any]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM state WHERE target = ?", (target,))
            row = cur.fetchone()
            return dict(row) if row else {"target": target, "consecutive_failures": 0}

    def update_state(self, target: str, **fields: Any) -> None:
        current = self.get_state(target)
        current.update(fields)
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO state (target, last_status, last_change_ts, consecutive_failures,"
                " last_alert_ts, dns_fingerprint, content_checksum) VALUES (?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(target) DO UPDATE SET last_status=excluded.last_status,"
                " last_change_ts=excluded.last_change_ts, consecutive_failures=excluded.consecutive_failures,"
                " last_alert_ts=excluded.last_alert_ts, dns_fingerprint=excluded.dns_fingerprint,"
                " content_checksum=excluded.content_checksum",
                (
                    target, current.get("last_status"), current.get("last_change_ts"),
                    int(current.get("consecutive_failures", 0)), current.get("last_alert_ts"),
                    current.get("dns_fingerprint"), current.get("content_checksum"),
                ),
            )

    # -- reads / analytics ------------------------------------------------- #
    def availability(self, target: str, *, hours: int = 24) -> dict[str, Any]:
        since = (utcnow().timestamp() - hours * 3600)
        with self._cursor() as cur:
            cur.execute(
                "SELECT ok, response_time_ms FROM results WHERE target = ?"
                " AND ts >= datetime(?, 'unixepoch')",
                (target, since),
            )
            rows = cur.fetchall()
        total = len(rows)
        if total == 0:
            return {"target": target, "samples": 0, "availability_pct": None,
                    "avg_ms": None, "max_ms": None, "min_ms": None, "failures": 0}
        up = sum(r["ok"] for r in rows)
        latencies = [r["response_time_ms"] for r in rows if r["response_time_ms"] is not None]
        return {
            "target": target,
            "samples": total,
            "availability_pct": round(100.0 * up / total, 3),
            "avg_ms": round(sum(latencies) / len(latencies), 1) if latencies else None,
            "max_ms": round(max(latencies), 1) if latencies else None,
            "min_ms": round(min(latencies), 1) if latencies else None,
            "failures": total - up,
        }

    def latency_series(self, target: str, *, hours: int = 24, limit: int = 200) -> list[dict[str, Any]]:
        since = (utcnow().timestamp() - hours * 3600)
        with self._cursor() as cur:
            cur.execute(
                "SELECT ts, response_time_ms, status FROM results WHERE target = ?"
                " AND ts >= datetime(?, 'unixepoch') ORDER BY ts DESC LIMIT ?",
                (target, since, limit),
            )
            return [dict(r) for r in reversed(cur.fetchall())]

    def _recent(self, table: str, limit: int) -> list[dict[str, Any]]:
        query = f"SELECT * FROM {_safe_table(table)} ORDER BY ts DESC LIMIT ?"  # noqa: S608
        with self._cursor() as cur:
            cur.execute(query, (limit,))
            return [dict(r) for r in cur.fetchall()]

    def recent_results(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return self._recent("results", limit)

    def recent_events(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return self._recent("events", limit)

    def recent_alerts(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return self._recent("alerts", limit)

    def purge(self, retention_days: int) -> int:
        if retention_days <= 0:
            return 0
        cutoff = utcnow().timestamp() - retention_days * 86400
        removed = 0
        with self._cursor() as cur:
            for table in sorted(_HISTORY_TABLES):
                query = f"DELETE FROM {_safe_table(table)} WHERE ts < datetime(?, 'unixepoch')"  # noqa: S608
                cur.execute(query, (cutoff,))
                removed += cur.rowcount
        return removed

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class NullDatabase:
    """No-op repository used when persistence is disabled."""

    def record_check(self, result: CheckResult) -> None: ...
    def record_result(self, result: TargetResult) -> None: ...
    def record_event(self, *a: Any, **k: Any) -> None: ...
    def record_alert(self, *a: Any, **k: Any) -> None: ...
    def get_state(self, target: str) -> dict[str, Any]:
        return {"target": target, "consecutive_failures": 0}
    def update_state(self, target: str, **fields: Any) -> None: ...
    def availability(self, target: str, *, hours: int = 24) -> dict[str, Any]:
        return {"target": target, "samples": 0, "availability_pct": None,
                "avg_ms": None, "max_ms": None, "min_ms": None, "failures": 0}
    def recent_results(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return []
    def recent_events(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return []
    def recent_alerts(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return []
    def latency_series(self, target: str, *, hours: int = 24, limit: int = 200) -> list[dict[str, Any]]:
        return []
    def purge(self, retention_days: int) -> int:
        return 0
    def close(self) -> None: ...
    def __enter__(self) -> NullDatabase:
        return self
    def __exit__(self, *exc: object) -> None: ...


def open_database(path: Path, *, enabled: bool = True) -> DatabaseLike:
    """Return a real :class:`Database` or a :class:`NullDatabase`."""
    return Database(path) if enabled else NullDatabase()
