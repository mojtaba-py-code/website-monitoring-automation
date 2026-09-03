# Contributing

Thanks for taking the time to contribute. This project aims to stay small,
typed and well-tested — the guidelines below exist to keep it that way.

## Getting set up

```bash
git clone https://github.com/mojtaba-py-code/website-monitoring-automation.git
cd website-monitoring-automation

python -m venv .venv
# Windows:  .venv\Scripts\activate
# Linux/mac: source .venv/bin/activate

pip install -e ".[dev,web,pdf]"
```

Use a virtual environment. Running `mypy` against a global site-packages
directory can surface errors from unrelated third-party stubs.

## Quality gates

Every change must pass all three locally before you open a pull request — CI
runs exactly the same commands on Linux, Windows and macOS across Python
3.10–3.12:

```bash
ruff check src tests      # lint, incl. flake8-bandit security rules
mypy                      # strict type-check
pytest --cov              # tests + coverage
```

## Conventions

* **Types everywhere.** `disallow_untyped_defs` is on; annotate every function.
* **No real network in tests.** HTTP is mocked with `respx`; ping/DNS/SSL are
  monkeypatched. A test that would open a socket to the internet will not be
  merged.
* **Dependency injection over globals.** Probes receive a `CheckContext`
  (settings + `UrlGuard`) so each one is unit-testable in isolation.
* **Docstrings explain *why*.** The *what* is usually visible in the code; the
  reasoning behind a guard or a workaround is not.
* **A probe must never raise.** Return a `CheckResult` with `Status.DOWN` and a
  useful message instead — one failing target must not stop a monitoring cycle.
* **Never log a secret.** Route anything that might carry one through
  `redact()` / `redact_url()` / `redact_headers()` first. When logging a failed
  outbound call, log the status code or exception *type*, never the URL.

## Adding a check

1. Create `src/webmon/checks/<name>_check.py` with an
   `async def check_<name>(target: Target, ctx: CheckContext) -> CheckResult`.
2. Validate the URL through `ctx.guard` (or fetch via `safe_fetch`, which does
   it for you plus per-hop redirect re-validation and the response-size cap).
3. Register it in `REGISTRY` in `src/webmon/checks/__init__.py`.
4. Add the literal to `CheckKind` in `src/webmon/config.py`.
5. Add tests, and document the new option in `docs/CONFIGURATION.md`.

## Pull requests

* Branch off `main`, keep the change focused, and explain the *why* in the
  description.
* Update the docs and `CHANGELOG.md` alongside the code.
* If your change touches the security model, say so explicitly — see
  [SECURITY.md](SECURITY.md).

## Reporting security issues

Please do **not** open a public issue. Follow [SECURITY.md](SECURITY.md).
