# Example outputs

Real artifacts from a monitoring run against two targets — one healthy
(`example.com`) and one deliberately unreachable — to show what you get without
running anything.

| File | Produced by |
|------|-------------|
| `example-config.yaml` | The config used for the run below |
| `example-report.html` | `webmon report` — self-contained HTML report |
| `example-report.json` | machine-readable report (summary + per-target stats) |
| `example-report.md` | Markdown summary table |
| `example-audit.log` | `logs/audit.log` — status-change / alert trail |

The run shows a mixed fleet: `Example Website` **up** (HTTP 200, valid TLS, DNS
resolves) and `Missing Service` **down** (host does not resolve), giving a 50%
health snapshot — exactly what an on-call engineer would triage.

Open `example-report.html` in a browser to see the styled, theme-aware report.
