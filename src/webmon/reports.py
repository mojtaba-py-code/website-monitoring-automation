"""Report generation in HTML, JSON, CSV, Markdown and (optionally) PDF."""

from __future__ import annotations

import csv
import html
import io
import json
from pathlib import Path
from typing import Any

from .database import DatabaseLike
from .logger import get_logger
from .models import TargetResult
from .utils import iso_now

logger = get_logger("reports")

_STATUS_COLOUR = {
    "up": "#1a7f37", "warning": "#9a6700", "degraded": "#bc4c00",
    "down": "#cf222e", "unknown": "#57606a",
}


def build_report(results: list[TargetResult], db: DatabaseLike, *, environment: str = "production") -> dict[str, Any]:
    """Assemble a normalised report document from a set of target results."""
    targets: list[dict[str, Any]] = []
    up = 0
    for result in results:
        stats = db.availability(result.target, hours=24)
        if result.ok:
            up += 1
        targets.append(
            {
                "name": result.target,
                "url": result.url,
                "status": result.status.value,
                "response_time_ms": result.response_time_ms,
                "availability_24h": stats.get("availability_pct"),
                "avg_ms": stats.get("avg_ms"),
                "max_ms": stats.get("max_ms"),
                "min_ms": stats.get("min_ms"),
                "failures_24h": stats.get("failures"),
                "checks": [c.to_dict() for c in result.checks],
            }
        )
    total = len(results)
    return {
        "meta": {"generated_at": iso_now(), "environment": environment},
        "summary": {
            "total": total,
            "up": up,
            "down": total - up,
            "health_pct": round(100.0 * up / total, 1) if total else None,
        },
        "targets": targets,
        "recent_events": db.recent_events(limit=25),
        "recent_alerts": db.recent_alerts(limit=25),
    }


class ReportGenerator:
    """Writes report documents in the requested formats."""

    def __init__(self, report_dir: Path) -> None:
        self._dir = report_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def write(self, report: dict[str, Any], formats: list[str], *, basename: str | None = None) -> dict[str, Path]:
        stem = basename or f"report_{iso_now().replace(':', '').replace('-', '')}"
        writers = {
            "json": self._json, "csv": self._csv, "html": self._html,
            "markdown": self._markdown, "pdf": self._pdf,
        }
        outputs: dict[str, Path] = {}
        for fmt in formats:
            writer = writers.get(fmt)
            if writer is None:
                logger.warning("Unknown report format ignored: %s", fmt)
                continue
            path = writer(report, stem)
            if path is not None:
                outputs[fmt] = path
                logger.info("Wrote %s report: %s", fmt, path)
        return outputs

    def _json(self, report: dict[str, Any], stem: str) -> Path:
        path = self._dir / f"{stem}.json"
        path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        return path

    def _csv(self, report: dict[str, Any], stem: str) -> Path:
        path = self._dir / f"{stem}.csv"
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["target", "url", "status", "response_time_ms", "availability_24h", "avg_ms", "failures_24h"])
        for t in report["targets"]:
            writer.writerow([t["name"], t["url"], t["status"], t["response_time_ms"],
                             t["availability_24h"], t["avg_ms"], t["failures_24h"]])
        path.write_text(buffer.getvalue(), encoding="utf-8")
        return path

    def _markdown(self, report: dict[str, Any], stem: str) -> Path:
        path = self._dir / f"{stem}.md"
        s = report["summary"]
        lines = [
            "# Website Monitoring Report",
            "",
            f"- **Generated:** {report['meta']['generated_at']}",
            f"- **Targets:** {s['total']} ({s['up']} up / {s['down']} down)",
            f"- **Health:** {s['health_pct']}%" if s["health_pct"] is not None else "- **Health:** n/a",
            "",
            "## Targets",
            "",
            "| Target | Status | Resp (ms) | Availability 24h | Failures 24h |",
            "| ------ | ------ | --------- | ---------------- | ------------ |",
        ]
        for t in report["targets"]:
            lines.append(
                f"| {t['name']} | {t['status']} | {t['response_time_ms'] or '-'} "
                f"| {t['availability_24h'] if t['availability_24h'] is not None else '-'}% "
                f"| {t['failures_24h'] if t['failures_24h'] is not None else '-'} |"
            )
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def _html(self, report: dict[str, Any], stem: str) -> Path:
        path = self._dir / f"{stem}.html"
        path.write_text(render_html(report), encoding="utf-8")
        return path

    def _pdf(self, report: dict[str, Any], stem: str) -> Path | None:
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
        except ImportError:
            logger.warning("PDF report requested but reportlab is not installed; skipping.")
            return None

        path = self._dir / f"{stem}.pdf"
        styles = getSampleStyleSheet()
        doc = SimpleDocTemplate(str(path), pagesize=A4, title="Website Monitoring Report")
        s = report["summary"]
        story: list[Any] = [
            Paragraph("Website Monitoring Report", styles["Title"]),
            Paragraph(f"Generated: {report['meta']['generated_at']}", styles["Normal"]),
            Paragraph(
                f"Targets: {s['total']} ({s['up']} up / {s['down']} down) — "
                f"Health: {s['health_pct']}%" if s["health_pct"] is not None else "Health: n/a",
                styles["Normal"],
            ),
            Spacer(1, 12),
        ]
        table_data = [["Target", "Status", "Resp (ms)", "Avail 24h", "Fail 24h"]]
        for t in report["targets"]:
            table_data.append([
                t["name"], t["status"], str(t["response_time_ms"] or "-"),
                f"{t['availability_24h']}%" if t["availability_24h"] is not None else "-",
                str(t["failures_24h"] if t["failures_24h"] is not None else "-"),
            ])
        table = Table(table_data, hAlign="LEFT")
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#24292f")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
        ]))
        story.append(table)
        doc.build(story)
        return path


def _c(status: str) -> str:
    return _STATUS_COLOUR.get(status, "#57606a")


def render_html(report: dict[str, Any]) -> str:
    """Render a self-contained, theme-aware HTML report."""
    esc = html.escape
    s = report["summary"]
    rows = []
    for t in report["targets"]:
        avail = f"{t['availability_24h']}%" if t["availability_24h"] is not None else "—"
        rt = f"{t['response_time_ms']:.0f}" if t["response_time_ms"] is not None else "—"
        rows.append(
            f"<tr><td>{esc(t['name'])}</td>"
            f"<td><span class='pill' style='background:{_c(t['status'])}'>{esc(t['status'])}</span></td>"
            f"<td>{esc(t['url'])}</td><td>{rt}</td><td>{avail}</td>"
            f"<td>{t['failures_24h'] if t['failures_24h'] is not None else '—'}</td></tr>"
        )
    events = "".join(
        f"<li>{esc(e.get('ts',''))} — <b>{esc(e.get('target',''))}</b>: "
        f"{esc(str(e.get('from_status')))} → {esc(str(e.get('to_status')))}</li>"
        for e in report.get("recent_events", [])[:15]
    )
    health = s["health_pct"]
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Website Monitoring Report</title>
<style>
 :root {{ color-scheme: light dark; }}
 body {{ font-family: system-ui,-apple-system,Segoe UI,sans-serif; margin:0; background:#f6f8fa; color:#1f2328; }}
 header {{ background:#24292f; color:#fff; padding:22px 28px; }}
 header h1 {{ margin:0; font-size:19px; }} header p {{ margin:4px 0 0; opacity:.8; font-size:13px; }}
 main {{ max-width:1000px; margin:22px auto; padding:0 16px; }}
 .cards {{ display:flex; gap:14px; flex-wrap:wrap; margin-bottom:16px; }}
 .card {{ background:#fff; border:1px solid #d0d7de; border-radius:10px; padding:14px 18px; flex:1; min-width:150px; }}
 .card .n {{ font-size:30px; font-weight:700; }} .card .l {{ font-size:12px; color:#57606a; }}
 table {{ width:100%; border-collapse:collapse; background:#fff; border:1px solid #d0d7de;
          border-radius:8px; overflow:hidden; font-size:13px; }}
 th,td {{ text-align:left; padding:8px 10px; border-bottom:1px solid #eaeef2; }} th {{ color:#57606a; }}
 .pill {{ color:#fff; padding:1px 8px; border-radius:20px; font-size:11px; text-transform:uppercase; }}
 h2 {{ font-size:15px; margin:22px 0 8px; }} ul {{ font-size:13px; }}
 @media (prefers-color-scheme: dark) {{
   body {{ background:#0d1117; color:#e6edf3; }} .card,table {{ background:#161b22; border-color:#30363d; }}
   th,td {{ border-color:#21262d; }} .card .l {{ color:#8b949e; }}
 }}
</style></head><body>
<header><h1>🌐 Website Monitoring Report</h1>
<p>{esc(report['meta']['generated_at'])} · {esc(report['meta']['environment'])}</p></header>
<main>
 <div class="cards">
   <div class="card"><div class="n">{s['total']}</div><div class="l">Targets</div></div>
   <div class="card"><div class="n" style="color:#1a7f37">{s['up']}</div><div class="l">Up</div></div>
   <div class="card"><div class="n" style="color:#cf222e">{s['down']}</div><div class="l">Down</div></div>
   <div class="card"><div class="n">{health if health is not None else '—'}%</div><div class="l">Health</div></div>
 </div>
 <table><tr><th>Target</th><th>Status</th><th>URL</th><th>Resp (ms)</th><th>Avail 24h</th><th>Fail 24h</th></tr>
 {''.join(rows)}</table>
 <h2>Recent status changes</h2>
 <ul>{events or '<li>None recorded.</li>'}</ul>
</main></body></html>
"""
