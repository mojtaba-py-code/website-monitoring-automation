# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] — 2026-09-03

Initial public release.

### Added

* **Async probes** — `http`, `api`, `ssl`, `dns`, `ping`, `port` and `content`
  checks, run concurrently under a bounded semaphore.
* **SSRF guard** — scheme allow-list, host block/allow-lists, private/loopback/
  link-local/reserved IP rejection, and per-hop redirect re-validation so an
  open redirect cannot pivot a probe onto an internal service. The block-list is
  enforced against resolved addresses as well as the hostname.
* **Secret hygiene** — `${ENV:VAR}` config placeholders, plus redaction of
  tokens, passwords, URL user-info and sensitive query parameters from logs.
* **Verified SMTP TLS** — the e-mail channel supplies its own SSL context so the
  certificate chain *and* hostname are verified (`smtplib`'s default STARTTLS
  context verifies neither), supports implicit TLS on port 465, and refuses to
  authenticate over an unencrypted session.
* **Alerting** — Telegram, Slack, Discord, e-mail and HMAC-signed generic
  webhooks, with flap-suppression, re-notification throttling and recovery
  notices.
* **History & analytics** — SQLite store of checks, results, events and alerts,
  with availability/latency aggregation and configurable retention.
* **Reports** — HTML, JSON, CSV, Markdown and PDF output.
* **Dashboard, REST API and metrics** — a FastAPI live dashboard, a read-only
  JSON API, and a dependency-free Prometheus `/metrics` endpoint. When
  `web.api_token` is set it gates every data route; browsers exchange the token
  for an HttpOnly, SameSite=Strict session cookie at `/login`. The server
  refuses to bind to a non-localhost interface without a token.
* **Deployment** — multi-stage Dockerfile running as a non-root user, Compose
  stack, systemd unit and cron / Task Scheduler snippets.
* **Quality gates** — ruff (including flake8-bandit security rules), mypy in
  strict mode, and 116 tests at ~84% coverage, run on Linux, Windows and macOS
  across Python 3.10–3.12. No test touches the real network.

[1.0.0]: https://github.com/mojtaba-py-code/website-monitoring-automation/releases/tag/v1.0.0
