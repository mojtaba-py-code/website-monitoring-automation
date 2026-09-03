# Developer Guide

## Setup

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[dev,web,pdf]"
```

## Quality gates

```bash
ruff check src tests      # lint, import order, async & security rules
mypy                      # strict type-check (src/webmon)
pytest --cov              # tests + coverage
```

All three must stay green. Config lives in `pyproject.toml`. mypy runs strict;
ruff enforces `E,F,W,I,N,UP,B,C4,SIM,PTH,ASYNC,RUF,S` — `S` being flake8-bandit,
so security linting is a standing gate rather than a one-off audit.

Work inside the virtual environment. `mypy` resolves imports from whatever
site-packages is active, so running it against a global interpreter can surface
errors from unrelated third-party stubs.

Beyond these three, CI also builds the package (`twine check` + a clean-install
smoke test), builds the Docker image, runs `pip-audit` against
`requirements.txt`, and runs CodeQL.

## Layout

```
src/webmon/
  config.py       typed settings (pydantic) + ${ENV:VAR} resolution
  security.py     UrlGuard (SSRF) + secret redaction
  models.py       Status enum, CheckResult, TargetResult
  checks/         probes: http, api, ssl, dns, port, ping, content
    base.py       CheckContext (effective settings, auth headers)
    httpclient.py safe_fetch — SSRF-safe redirect following + size cap
  database.py     SQLite repository (+ NullDatabase)
  alerting/       Alert model, channels, AlertManager (flap-suppression)
  monitor.py      MonitorService orchestrator (async)
  scheduler.py    per-target async loops + cron/schtasks emitters
  reports.py      HTML/JSON/CSV/Markdown/PDF
  metrics.py      Prometheus text exposition (no dependency)
  cli.py          argparse front-end
  web/            FastAPI dashboard + REST API + /metrics
```

## Testing

Tests never touch the network:

* **HTTP** is mocked with `respx` (`@respx.mock`).
* **Targets** use loopback IPs with `block_private_networks: false`.
* **SSL** uses an in-memory self-signed cert (no handshake).
* **DNS** resolver is monkeypatched; **ports** run against a local server.
* **SMTP** is driven through a fake `smtplib.SMTP` that records the TLS context.

`pytest-asyncio` is in auto mode, so `async def test_*` just works. Fixtures
(`tests/conftest.py`): `settings`, `ctx`, `service`, plus per-file `cli_config`.

```bash
pytest -m integration          # only integration tests
pytest tests/test_http_checks.py
pytest --cov --cov-report=html && open htmlcov/index.html
```

## Adding a probe

1. Create `src/webmon/checks/<kind>_check.py` with:
   `async def check_<kind>(target: Target, ctx: CheckContext) -> CheckResult`.
2. Fetch via `httpclient.safe_fetch` (for HTTP) so the SSRF guard applies, or
   validate the URL with `ctx.guard.validate(...)` for raw sockets.
3. Register it in `checks/__init__.py::REGISTRY`.
4. Add unit tests (probe in isolation) and, if relevant, extend the monitor
   integration test. Keep ruff/mypy/pytest green.

## Adding an alert channel

Implement `alerting.base.Notifier` (async `send`), build it in
`AlertManager._build_channels`, and add its config model under
`config.AlertChannels`. Never log exception text for web channels (it can embed
secrets) — log a status code / error type only.

## Releasing

1. Bump `__version__` (`src/webmon/__init__.py`) and `project.version`
   (`pyproject.toml`) — they must match.
2. Add the release section to [`CHANGELOG.md`](../CHANGELOG.md).
3. Tag (`git tag -a v1.0.0 -m "v1.0.0"`) and push the tag.

CI runs the full matrix on Windows/Linux/macOS × Python 3.10–3.12, plus the
package, Docker and security jobs.
