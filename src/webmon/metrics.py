"""Prometheus metrics exposition (dependency-free).

Emits the standard text exposition format by hand -- no ``prometheus_client``
dependency required. The web layer serves this at ``/metrics`` so Prometheus /
Grafana can scrape uptime, latency and availability per target.
"""

from __future__ import annotations

from .database import DatabaseLike
from .models import Status, TargetResult

_STATUS_VALUE = {
    Status.UP: 1,
    Status.WARNING: 1,
    Status.DEGRADED: 0,
    Status.DOWN: 0,
    Status.UNKNOWN: 0,
}


def _escape(label: str) -> str:
    """Escape a label value per the exposition format (backslash, quote, newline)."""
    return label.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def render_metrics(results: dict[str, TargetResult], db: DatabaseLike) -> str:
    """Render current target results + availability as Prometheus text.

    Samples are grouped by metric family, each preceded by its own HELP and TYPE
    lines, as the exposition format requires (a family must not be interleaved
    with another).
    """
    up_samples: list[str] = []
    latency_samples: list[str] = []
    availability_samples: list[str] = []

    for name, result in sorted(results.items()):
        label = f'target="{_escape(name)}"'
        up_samples.append(f"webmon_up{{{label}}} {_STATUS_VALUE[result.status]}")
        if result.response_time_ms is not None:
            latency_samples.append(f"webmon_response_time_ms{{{label}}} {result.response_time_ms}")
        avail = db.availability(name, hours=24).get("availability_pct")
        if avail is not None:
            availability_samples.append(f"webmon_availability_ratio{{{label}}} {avail / 100.0:.5f}")

    families = (
        ("webmon_up", "Target is up (1) or down (0).", up_samples),
        ("webmon_response_time_ms", "Last response time in milliseconds.", latency_samples),
        ("webmon_availability_ratio", "Availability over the last 24h (0-1).", availability_samples),
    )
    lines: list[str] = []
    for metric, help_text, samples in families:
        lines.append(f"# HELP {metric} {help_text}")
        lines.append(f"# TYPE {metric} gauge")
        lines.extend(samples)
    return "\n".join(lines) + "\n"
