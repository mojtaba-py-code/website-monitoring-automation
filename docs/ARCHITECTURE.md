# Architecture

## Principles

* **Async-first.** Monitoring is I/O-bound; probes run concurrently on a single
  event loop, bounded by a semaphore (`performance.max_concurrency`).
* **Secure by construction.** Every outbound request passes the SSRF `UrlGuard`;
  redirects are re-validated; secrets are redacted before logging.
* **Clean layering.** A thin CLI/web/scheduler layer calls one service
  orchestrator, which composes independent probes and a repository.
* **Testable.** No global state; config and the guard are injected. HTTP is
  mocked in tests (`respx`) so the suite never touches the network.

## Layers

```
        ┌──────────┐   ┌───────────────┐   ┌──────────────┐
 entry  │  cli.py  │   │ web/server.py │   │ scheduler.py │
        │(argparse)│   │  (FastAPI)    │   │  (asyncio)   │
        └────┬─────┘   └──────┬────────┘   └──────┬───────┘
             └────────────┬───┴───────────────────┘
                          ▼
               ┌────────────────────────┐
 orchestration │      monitor.py        │  MonitorService
               │  (run_once / _process) │
               └───────────┬────────────┘
        ┌──────────┬───────┼─────────┬───────────┐
        ▼          ▼       ▼         ▼           ▼
     checks/    security  database  alerting   reports /
     (probes)   UrlGuard  (SQLite)  (channels) metrics
```

## Key components

### `security.py` — `UrlGuard`
The single choke point for "may I request this URL?". Validates scheme, host
block/allow-lists, and (optionally) that resolved IPs are public. Also holds the
`redact*` helpers that scrub secrets from strings/URLs/headers before logging.

### `checks/` — probes
Each probe is an async `(target, ctx) -> CheckResult`. `httpclient.safe_fetch`
centralises SSRF-safe fetching: manual redirect following with per-hop
validation and a response-size cap. Probes are registered in `checks/REGISTRY`.

### `monitor.py` — `MonitorService`
Runs a target's checks concurrently, aggregates them into a `TargetResult`
(worst-status wins), persists results, records state-change events, performs
DNS/content change detection, and drives alerting. `run_once()` fans out across
all targets; the scheduler and dashboard reuse it.

### `alerting/` — decision + dispatch
`AlertManager.decide()` encodes flap-suppression: alert only after
`failure_threshold` consecutive failures, re-notify at most every
`renotify_seconds`, and emit a recovery notice on return to health.
`dispatch()` fans out to channels concurrently; a failed channel never raises.

### `database.py` — repository
SQLite via stdlib `sqlite3` (parameterised queries only). Stores checks,
results, events, alerts and per-target `state`. A `NullDatabase` no-op keeps
callers branch-free when persistence is disabled.

## Data flow (one cycle)

1. `run_once()` selects enabled targets and fans out `_do(target)`.
2. `check_target()` runs the target's probes concurrently under the semaphore.
3. `_process()` applies change detection, persists results/checks, records a
   state-change event on transition, updates the failure counter, and asks the
   `AlertManager` whether to alert — dispatching and recording if so.
4. State (status, failures, DNS fingerprint, content checksum, last-alert time)
   is upserted for the next cycle.

## Concurrency & resilience

* One `asyncio` task per target loop in `scheduler.py`; a failure in one loop is
  logged and never stops the others.
* Every probe is wrapped so an unexpected exception becomes a `DOWN` result, not
  a crashed cycle.
* Response bodies are size-capped; requests carry connect + total timeouts.

## Extending

Add `checks/<kind>_check.py` with an async `check_<kind>` returning a
`CheckResult`, register it in `checks/REGISTRY`, and it becomes available to any
target's `checks:` list and the `ctx`-driven monitor with no other wiring.
