# CLI Guide

```
webmon [global options] <command> [command options]
```

## Global options
| Option | Description |
|--------|-------------|
| `--config PATH` | Config YAML/TOML (auto-discovered if omitted) |
| `--data-dir DIR` | Override base output directory |
| `--timeout SEC` | Override per-request timeout |
| `--interval SEC` | Override default interval |
| `--threads N` | Max concurrent checks |
| `--verbose` | DEBUG logging + tracebacks |
| `--silent` | Suppress console logging |
| `--json` / `--csv` / `--html` | Also write a report in that format |
| `--version` | Print version and exit |

Exit codes: `0` all healthy · `1` runtime error · `2` usage error · `3` one or
more targets unhealthy · `130` interrupted.

## Commands

### `check [names...]`
Run one monitoring cycle over configured targets (default: all enabled). Filter
by name. Returns `3` if any target is unhealthy.

```bash
webmon check
webmon check "Example Website"
webmon --json --html check
```

### `run`
Continuous scheduled monitoring — one loop per target on its own interval, plus
periodic history purge. Ctrl+C to stop.

### Ad-hoc single-target checks
Accept a URL or a bare host (defaults to `https://`).

```bash
webmon website example.com    # HTTP + SSL
webmon api https://api.example.com/health
webmon ssl example.com
webmon dns example.com
webmon ping example.com
webmon ports example.com 443 80 22
```

### `report`
Run a cycle and write reports (formats from `--json/--csv/--html` or config).

### `export [--format json|csv] [--limit N]`
Export recent monitoring history to `exports/`.

### `list`
List configured targets and their checks.

### `dashboard [--host H] [--port P]`
Launch the FastAPI dashboard + REST API + `/metrics` (requires the `web` extra).

### `schedule`
Print `cron` and Windows `schtasks` snippets that run `webmon check` on the
configured interval.

## Examples

```bash
# Quick production triage
webmon website myapp.com && echo healthy

# One cycle with an HTML report, quieter output
webmon --silent --html check

# Continuous monitoring in the background (Linux)
nohup webmon run >/var/log/webmon.out 2>&1 &
```
