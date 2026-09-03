# Troubleshooting

## "Refusing request to non-public address …"
The SSRF guard blocked a private/loopback/reserved IP. This is intentional. To
monitor an internal host you own, either set `security.block_private_networks:
false` or add the host to `security.allowlist_hosts`.

## "Host is block-listed: …"
The host is in `security.blocklist_hosts` (the cloud-metadata endpoint is there
by default). Remove it only if you truly need to monitor it.

## "Scheme not allowed"
The URL scheme is not in `security.allowed_schemes` (default `http`, `https`).
For ad-hoc commands you can pass a bare host (`webmon ports example.com`) — it
defaults to `https://`.

## A site shows DOWN but works in my browser
* Check the exact status code — the target's `expected_status` may not include
  it (e.g. a `403`/`401` behind auth). Configure `auth` or adjust the list.
* `expected_keywords` are **case-sensitive** and must all be present;
  `forbidden_keywords` must all be absent.
* The site may block the default User-Agent — set a custom `defaults.user_agent`
  or per-target `headers`.
* A redirect may land on a blocked host — see `logs/errors.log`.

## SSL check says DOWN
* Expired or not-yet-valid certificate, or a TLS handshake failure. Run
  `webmon ssl <host>` for the exact reason and the issuer/expiry details.
* Self-signed/internal CAs will fail default verification; that is expected for
  public monitoring.

## DNS check returns nothing
* Confirm the host actually has the requested record types
  (`dns_record_types`). Use `webmon dns <host>` to see what resolves.
* Custom `defaults.dns_servers` must be reachable.

## Ping always DOWN on Linux containers
Some container images/hosts restrict ICMP. Ping shells out to the system `ping`
utility; if ICMP is blocked, rely on `http`/`port` checks instead.

## Alerts aren't sent
* `alerting.enabled` and the specific channel's `enabled` must be `true`.
* Secrets come from `${ENV:VAR}` — verify they are exported.
* Alerts only fire after `failure_threshold` consecutive failures, and re-notify
  at most every `renotify_seconds`.
* Delivery failures log only a status code / error type (never the token) — an
  HTTP 401/404 in `logs/errors.log` usually means a bad token/webhook URL.

## Dashboard won't start
Install the extra: `pip install -e ".[web]"`. If the port is busy, pick another
with `--port`. It binds to `127.0.0.1` by default.

## PDF report skipped
Install the extra: `pip install -e ".[pdf]"` (reportlab). Without it, PDF is
silently skipped and the other formats are still written.

## High memory / slow cycles
* Lower `performance.max_concurrency`.
* Reduce `defaults.max_response_bytes` for large pages.
* Split very large target lists or increase intervals.

## Where are the logs?
`logs/webmon-YYYY-MM-DD.log` (all), `logs/errors.log` (warnings+),
`logs/audit.log` (status changes and alerts). Use `--verbose` for DEBUG.
