"""Command-line interface for Website Monitoring Automation.

A thin ``argparse`` front-end over :class:`~webmon.monitor.MonitorService`.
Global options (``--config``, ``--timeout``, ``--interval``, ``--threads``,
``--verbose``, ``--silent``, ``--json/--csv/--html``) apply to every subcommand.

Exit codes: ``0`` all healthy · ``1`` runtime error · ``2`` usage error ·
``3`` one or more targets unhealthy · ``130`` interrupted.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
from collections.abc import Sequence

from . import __version__
from .config import ConfigError, Settings, Target, find_default_config, load_settings
from .models import Status, TargetResult
from .monitor import MonitorService


def _enable_utf8_console() -> None:
    """Make stdout/stderr UTF-8 tolerant so glyphs never crash on Windows."""
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]


_enable_utf8_console()

try:
    from rich.console import Console
    from rich.table import Table

    _console: Console | None = Console()
except Exception:  # pragma: no cover
    _console = None

_STATUS_STYLE = {
    Status.UP: "green", Status.WARNING: "yellow", Status.DEGRADED: "dark_orange",
    Status.DOWN: "red", Status.UNKNOWN: "dim",
}


# --------------------------------------------------------------------------- #
# Output helpers
# --------------------------------------------------------------------------- #
def _print(message: str = "", *, style: str | None = None) -> None:
    if _console is not None:
        _console.print(message, style=style)
    else:  # pragma: no cover
        print(message)


def _error(message: str) -> None:
    if _console is not None:
        _console.print(f"[bold red]error:[/] {message}")
    else:  # pragma: no cover
        print(f"error: {message}", file=sys.stderr)


def _results_table(results: list[TargetResult]) -> None:
    if _console is None:  # pragma: no cover
        for r in results:
            print(f"{r.status.value:8} {r.target} {r.url}")
        return
    table = Table(title="Monitoring Results", header_style="bold cyan")
    table.add_column("Target")
    table.add_column("Status")
    table.add_column("Resp (ms)")
    table.add_column("Details")
    for r in results:
        style = _STATUS_STYLE.get(r.status, "")
        rt = f"{r.response_time_ms:.0f}" if r.response_time_ms is not None else "-"
        detail = "; ".join(f"{c.kind}:{c.status.value}" for c in r.checks) or "-"
        table.add_row(r.target, f"[{style}]{r.status.value}[/]", rt, detail)
    _console.print(table)


# --------------------------------------------------------------------------- #
# Bootstrap
# --------------------------------------------------------------------------- #
def _load(args: argparse.Namespace) -> Settings:
    settings = load_settings(args.config or find_default_config(), base_dir=args.data_dir)
    if args.verbose:
        settings.logging.level = "DEBUG"
    if args.timeout:
        settings.defaults.timeout_seconds = args.timeout
    if args.interval:
        settings.defaults.interval_seconds = args.interval
    if args.threads:
        settings.performance.max_concurrency = args.threads
    return settings


def _report_formats(args: argparse.Namespace) -> list[str]:
    formats: list[str] = []
    if args.json:
        formats.append("json")
    if args.csv:
        formats.append("csv")
    if args.html:
        formats.append("html")
    return formats


def _adhoc_target(url: str, checks: list[str], *, ports: list[int] | None = None) -> Target:
    # Accept a bare host (e.g. "example.com") for convenience by defaulting to https.
    if "://" not in url:
        url = f"https://{url}"
    return Target(name=url, url=url, checks=checks, ports=ports or [])  # type: ignore[arg-type]


def _write_reports_if_requested(service: MonitorService, results: list[TargetResult], args: argparse.Namespace) -> None:
    formats = _report_formats(args)
    if not formats:
        return
    from .reports import ReportGenerator, build_report

    report = build_report(results, service.db, environment=service.settings.app.environment)
    paths = ReportGenerator(service.settings.report_dir).write(report, formats)
    if paths:
        _print("Reports: " + ", ".join(f"{k} -> {v}" for k, v in paths.items()), style="dim")


# --------------------------------------------------------------------------- #
# Command handlers
# --------------------------------------------------------------------------- #
def cmd_check(service: MonitorService, args: argparse.Namespace) -> int:
    names = set(args.targets or [])
    targets = [t for t in service.settings.enabled_targets() if not names or t.name in names]
    if not targets:
        _error("No matching enabled targets in configuration.")
        return 1
    results = asyncio.run(service.run_once(targets))
    _results_table(results)
    _write_reports_if_requested(service, results, args)
    return 0 if all(r.ok for r in results) else 3


def _run_adhoc(service: MonitorService, target: Target) -> int:
    result = asyncio.run(service.check_target(target))
    _results_table([result])
    for check in result.checks:
        _print(f"  [dim]{check.kind}[/]: {check.message}")
    return 0 if result.ok else 3


def cmd_website(service: MonitorService, args: argparse.Namespace) -> int:
    return _run_adhoc(service, _adhoc_target(args.url, ["http", "ssl"]))


def cmd_api(service: MonitorService, args: argparse.Namespace) -> int:
    return _run_adhoc(service, _adhoc_target(args.url, ["api"]))


def cmd_ssl(service: MonitorService, args: argparse.Namespace) -> int:
    return _run_adhoc(service, _adhoc_target(args.url, ["ssl"]))


def cmd_dns(service: MonitorService, args: argparse.Namespace) -> int:
    return _run_adhoc(service, _adhoc_target(args.url, ["dns"]))


def cmd_ping(service: MonitorService, args: argparse.Namespace) -> int:
    return _run_adhoc(service, _adhoc_target(args.url, ["ping"]))


def cmd_ports(service: MonitorService, args: argparse.Namespace) -> int:
    return _run_adhoc(service, _adhoc_target(args.url, ["port"], ports=args.ports))


def cmd_run(service: MonitorService, args: argparse.Namespace) -> int:
    from .scheduler import SchedulerService

    _print("Starting continuous monitoring (Ctrl+C to stop)…")
    try:
        asyncio.run(SchedulerService(service).run())
    except KeyboardInterrupt:  # pragma: no cover - interactive
        _print("\nStopped.")
    return 0


def cmd_report(service: MonitorService, args: argparse.Namespace) -> int:
    from .reports import ReportGenerator, build_report

    results = asyncio.run(service.run_once())
    formats = _report_formats(args) or service.settings.report.formats
    report = build_report(results, service.db, environment=service.settings.app.environment)
    paths = ReportGenerator(service.settings.report_dir).write(report, list(formats))
    _results_table(results)
    for fmt, path in paths.items():
        _print(f"  {fmt} -> {path}")
    return 0


def cmd_export(service: MonitorService, args: argparse.Namespace) -> int:
    import csv
    import json

    export_dir = service.settings.export_dir
    export_dir.mkdir(parents=True, exist_ok=True)
    results = service.db.recent_results(limit=args.limit)
    if args.format == "json":
        path = export_dir / "history.json"
        path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    else:
        path = export_dir / "history.csv"
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["target", "url", "status", "ok", "response_time_ms", "ts"])
            for r in results:
                writer.writerow([r.get("target"), r.get("url"), r.get("status"),
                                 r.get("ok"), r.get("response_time_ms"), r.get("ts")])
    _print(f"Exported {len(results)} rows -> {path}")
    return 0


def cmd_list(service: MonitorService, args: argparse.Namespace) -> int:
    if _console is None:  # pragma: no cover
        for t in service.settings.targets:
            print(t.name, t.url)
        return 0
    table = Table(title="Configured Targets", header_style="bold cyan")
    table.add_column("Name")
    table.add_column("URL")
    table.add_column("Checks")
    table.add_column("Enabled")
    for t in service.settings.targets:
        table.add_row(t.name, t.url, ", ".join(t.checks), "yes" if t.enabled else "no")
    _console.print(table)
    return 0


def cmd_dashboard(service: MonitorService, args: argparse.Namespace) -> int:
    try:
        from .web.server import run_server
    except ImportError as exc:
        _error(f"Web dependencies not installed: {exc}. Install: pip install -e \".[web]\"")
        return 1
    host = args.host or service.settings.web.host
    port = args.port or service.settings.web.port
    _print(f"Dashboard on http://{host}:{port} (Ctrl+C to stop)")
    run_server(service.settings, host=host, port=port)
    return 0


def cmd_schedule(service: MonitorService, args: argparse.Namespace) -> int:
    from .scheduler import cron_line, windows_task_command

    minutes = max(1, (args.interval or service.settings.defaults.interval_seconds) // 60)
    _print("[bold]Native scheduler equivalents (runs one cycle each tick):[/]")
    _print("  cron:    " + cron_line("webmon check", minutes))
    _print("  windows: " + windows_task_command("WebmonCheck", "webmon check", minutes))
    return 0


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="webmon",
        description="Website Monitoring Automation — async uptime / SSL / DNS / API monitoring.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--config", metavar="PATH", help="Config YAML/TOML (auto-discovered if omitted).")
    parser.add_argument("--data-dir", metavar="DIR", help="Override base output directory.")
    parser.add_argument("--timeout", type=float, metavar="SEC", help="Override per-request timeout.")
    parser.add_argument("--interval", type=int, metavar="SEC", help="Override default interval.")
    parser.add_argument("--threads", type=int, metavar="N", help="Max concurrent checks.")
    parser.add_argument("--verbose", action="store_true", help="DEBUG logging.")
    parser.add_argument("--silent", action="store_true", help="Suppress console logging.")
    parser.add_argument("--json", action="store_true", help="Also write a JSON report.")
    parser.add_argument("--csv", action="store_true", help="Also write a CSV report.")
    parser.add_argument("--html", action="store_true", help="Also write an HTML report.")

    sub = parser.add_subparsers(dest="command", metavar="<command>", required=True)

    p_check = sub.add_parser("check", help="Run one monitoring cycle over configured targets.")
    p_check.add_argument("targets", nargs="*", help="Target names to check (default: all enabled).")
    p_check.set_defaults(func=cmd_check)

    sub.add_parser("run", help="Run continuous scheduled monitoring.").set_defaults(func=cmd_run)

    for name, func, help_text in [
        ("website", cmd_website, "Ad-hoc check a URL (HTTP + SSL)."),
        ("api", cmd_api, "Ad-hoc check a JSON API endpoint."),
        ("ssl", cmd_ssl, "Ad-hoc check a site's TLS certificate."),
        ("dns", cmd_dns, "Ad-hoc resolve a host's DNS records."),
        ("ping", cmd_ping, "Ad-hoc ping a host."),
    ]:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("url", help="URL or host to check.")
        p.set_defaults(func=func)

    p_ports = sub.add_parser("ports", help="Ad-hoc TCP port check.")
    p_ports.add_argument("url", help="URL or host.")
    p_ports.add_argument("ports", nargs="*", type=int, help="Ports (default 80/443).")
    p_ports.set_defaults(func=cmd_ports)

    sub.add_parser("report", help="Run a cycle and write reports.").set_defaults(func=cmd_report)

    p_export = sub.add_parser("export", help="Export monitoring history.")
    p_export.add_argument("--format", choices=["json", "csv"], default="json")
    p_export.add_argument("--limit", type=int, default=500)
    p_export.set_defaults(func=cmd_export)

    sub.add_parser("list", help="List configured targets.").set_defaults(func=cmd_list)

    p_dash = sub.add_parser("dashboard", help="Launch the web dashboard + REST API.")
    p_dash.add_argument("--host", help="Bind host.")
    p_dash.add_argument("--port", type=int, help="Bind port.")
    p_dash.set_defaults(func=cmd_dashboard)

    sub.add_parser("schedule", help="Print cron / Task Scheduler equivalents.").set_defaults(func=cmd_schedule)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        settings = _load(args)
    except ConfigError as exc:
        _error(str(exc))
        return 1

    service: MonitorService | None = None
    try:
        service = MonitorService(settings, silent=args.silent)
        return int(args.func(service, args))
    except KeyboardInterrupt:  # pragma: no cover - interactive
        _error("Interrupted.")
        return 130
    except Exception as exc:
        _error(f"{type(exc).__name__}: {exc}")
        if args.verbose and _console is not None:
            _console.print_exception()
        return 1
    finally:
        if service is not None:
            service.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
