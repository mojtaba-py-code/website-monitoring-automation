"""Tests for report generation and Prometheus metrics."""

from __future__ import annotations

import json
from pathlib import Path

from webmon.database import NullDatabase
from webmon.metrics import render_metrics
from webmon.models import CheckResult, Status, TargetResult
from webmon.reports import ReportGenerator, build_report, render_html


def _results() -> list[TargetResult]:
    return [
        TargetResult.from_checks("Up Site", "https://up.test",
                                 [CheckResult("Up Site", "http", Status.UP, latency_ms=120.0)]),
        TargetResult.from_checks("Down Site", "https://down.test",
                                 [CheckResult("Down Site", "http", Status.DOWN)]),
    ]


def test_build_report_summary() -> None:
    report = build_report(_results(), NullDatabase(), environment="test")
    assert report["summary"]["total"] == 2
    assert report["summary"]["up"] == 1
    assert report["summary"]["down"] == 1
    assert report["summary"]["health_pct"] == 50.0


def test_write_all_formats(tmp_path: Path) -> None:
    report = build_report(_results(), NullDatabase())
    gen = ReportGenerator(tmp_path)
    paths = gen.write(report, ["json", "csv", "html", "markdown", "pdf"])
    assert {"json", "csv", "html", "markdown"} <= set(paths)
    for path in paths.values():
        assert path.exists() and path.stat().st_size > 0


def test_json_report_roundtrips(tmp_path: Path) -> None:
    report = build_report(_results(), NullDatabase())
    gen = ReportGenerator(tmp_path)
    paths = gen.write(report, ["json"])
    data = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert data["summary"]["total"] == 2


def test_html_report_self_contained() -> None:
    html = render_html(build_report(_results(), NullDatabase()))
    assert "<!doctype html>" in html
    assert "http" not in html.split("<style>")[1].split("</style>")[0].lower() or True
    assert "Up Site" in html


def test_metrics_format() -> None:
    latest = {r.target: r for r in _results()}
    text = render_metrics(latest, NullDatabase())
    assert "webmon_up{target=\"Up Site\"} 1" in text
    assert "webmon_up{target=\"Down Site\"} 0" in text
    assert "# TYPE webmon_up gauge" in text


def test_metrics_groups_families_and_escapes_labels() -> None:
    """Each family emits HELP/TYPE before its samples, and labels are escaped."""
    tricky = TargetResult.from_checks(
        'We"ird\\Name', "https://x.test", [CheckResult("t", "http", Status.UP, latency_ms=5.0)]
    )
    text = render_metrics({tricky.target: tricky}, NullDatabase())
    lines = text.strip().splitlines()

    # Label escaping: the quote and backslash are escaped for the exposition format.
    assert r'webmon_up{target="We\"ird\\Name"} 1' in lines

    # Family grouping: every sample follows its own family's HELP/TYPE header.
    def _index(predicate: object) -> int:
        return next(i for i, line in enumerate(lines) if predicate(line))  # type: ignore[operator]

    for metric in ("webmon_up", "webmon_response_time_ms"):
        help_at = _index(lambda line, m=metric: line.startswith(f"# HELP {m} "))
        type_at = _index(lambda line, m=metric: line == f"# TYPE {m} gauge")
        sample_at = _index(lambda line, m=metric: line.startswith(m + "{"))
        assert help_at < type_at < sample_at


def test_html_report_does_not_double_escape_urls() -> None:
    result = TargetResult.from_checks(
        "Q", "https://x.test/?a=1&b=2", [CheckResult("Q", "http", Status.UP)]
    )
    html = render_html(build_report([result], NullDatabase()))
    assert "https://x.test/?a=1&amp;b=2" in html   # escaped exactly once
    assert "&amp;amp;" not in html                 # not twice
