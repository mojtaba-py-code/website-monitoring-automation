"""Shared domain models: check statuses and result value objects.

Every probe returns a :class:`CheckResult`; the monitor aggregates the results
for one target into a :class:`TargetResult` with an overall :class:`Status`.
These objects are plain, serialisable dataclasses so the database, reports, API
and alerting layers all speak the same language.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from .utils import iso_now


class Status(str, Enum):
    """Health status of a check or target (ordered worst-last for aggregation)."""

    UP = "up"
    WARNING = "warning"      # working but attention needed (e.g. SSL expiring soon)
    DEGRADED = "degraded"    # working but slow / partial
    DOWN = "down"
    UNKNOWN = "unknown"

    @property
    def is_healthy(self) -> bool:
        return self in (Status.UP, Status.WARNING)


# Severity ranking used to pick the worst status across a target's checks.
_SEVERITY = {
    Status.UP: 0,
    Status.WARNING: 1,
    Status.DEGRADED: 2,
    Status.UNKNOWN: 3,
    Status.DOWN: 4,
}


def worst(statuses: list[Status]) -> Status:
    """Return the most severe status in ``statuses`` (empty -> UNKNOWN)."""
    if not statuses:
        return Status.UNKNOWN
    return max(statuses, key=lambda s: _SEVERITY[s])


@dataclass(slots=True)
class CheckResult:
    """The outcome of a single probe against a target."""

    target: str
    kind: str
    status: Status
    latency_ms: float | None = None
    message: str = ""
    timestamp: str = field(default_factory=iso_now)
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status.is_healthy

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        data["ok"] = self.ok
        return data


@dataclass(slots=True)
class TargetResult:
    """Aggregated result of all checks run against one target in a cycle."""

    target: str
    url: str
    status: Status
    checks: list[CheckResult] = field(default_factory=list)
    timestamp: str = field(default_factory=iso_now)

    @classmethod
    def from_checks(cls, target: str, url: str, checks: list[CheckResult]) -> TargetResult:
        overall = worst([c.status for c in checks])
        return cls(target=target, url=url, status=overall, checks=checks)

    @property
    def ok(self) -> bool:
        return self.status.is_healthy

    @property
    def response_time_ms(self) -> float | None:
        """Latency of the primary HTTP/API check, if present."""
        for check in self.checks:
            if check.kind in ("http", "api") and check.latency_ms is not None:
                return check.latency_ms
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "url": self.url,
            "status": self.status.value,
            "ok": self.ok,
            "timestamp": self.timestamp,
            "response_time_ms": self.response_time_ms,
            "checks": [c.to_dict() for c in self.checks],
        }
