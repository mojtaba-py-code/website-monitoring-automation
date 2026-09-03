# Configuration Guide

Copy `config/config.example.yaml` to `config/config.yaml` (git-ignored) and
edit. TOML is also supported (`--config config/config.toml`). Secrets must be
referenced as `${ENV:VAR}` and are resolved from the environment at load time.

## `defaults`
Applied to every target unless overridden per-target.

| Key | Default | Meaning |
|-----|---------|---------|
| `interval_seconds` | 60 | How often to check each target |
| `timeout_seconds` | 10 | Per-request timeout |
| `retries` / `retry_backoff_seconds` | 2 / 0.5 | Transient-failure retries |
| `verify_ssl` | true | Validate TLS on HTTP checks |
| `follow_redirects` / `max_redirects` | true / 5 | Redirect handling |
| `max_response_bytes` | 5 MiB | Response body cap |
| `ssl_warning_days` | 21 | Warn when a cert expires within N days |
| `domain_warning_days` | 30 | Warn when a domain expires within N days |
| `max_response_time_ms` | 3000 | "slow" (DEGRADED) threshold |
| `user_agent` | … | Request User-Agent |
| `dns_servers` | [] | Custom resolvers (empty = system) |

## `performance`
| Key | Default | Meaning |
|-----|---------|---------|
| `max_concurrency` | 20 | Max simultaneous checks (semaphore) |
| `connect_timeout_seconds` | 5 | TCP connect timeout |

## `security` (SSRF guard)
| Key | Default | Meaning |
|-----|---------|---------|
| `allowed_schemes` | `[http, https]` | Permitted URL schemes |
| `block_private_networks` | true | Refuse private/loopback/link-local/reserved IPs |
| `validate_redirects` | true | Re-check each redirect hop |
| `allowlist_hosts` | [] | Hosts allowed despite the private-network block |
| `blocklist_hosts` | `[169.254.169.254]` | Always-refused hosts |

> Keep `block_private_networks: true` for internet monitoring. Set it to `false`
> **only** to intentionally monitor an internal network you own.

## `targets`
A list; each entry:

| Key | Meaning |
|-----|---------|
| `name`, `url`, `enabled` | Identity and on/off |
| `checks` | Any of `http, ssl, dns, ping, port, content, api` |
| `expected_status` | Acceptable HTTP status codes |
| `expected_keywords` / `forbidden_keywords` | Must / must-not appear in the body |
| `content_hash_check` | Alert when the page checksum changes |
| `dns_record_types` | e.g. `[A, AAAA, MX]` |
| `ports` | TCP ports for the `port` check |
| `json_path_checks` | `[{path: "status", equals: "ok"}]` for `api` checks |
| `headers` | Extra request headers |
| `auth` | `type: none|basic|bearer|apikey` (+ `${ENV:...}` secrets) |
| Overrides | `interval_seconds`, `timeout_seconds`, `verify_ssl`, `follow_redirects`, `max_response_time_ms`, `ssl_warning_days` |

## `alerting`
| Key | Default | Meaning |
|-----|---------|---------|
| `enabled` | false | Master switch |
| `failure_threshold` | 2 | Alert after N consecutive failures |
| `notify_on_recovery` | true | Emit a recovery notice |
| `renotify_seconds` | 3600 | Re-send an ongoing alert at most this often (0 = only on change) |
| `channels.*` | disabled | `email`, `telegram`, `slack`, `discord`, `webhook` (HMAC-signed) |

### `channels.email`
| Key | Default | Meaning |
|-----|---------|---------|
| `smtp_host` / `smtp_port` | — / 587 | SMTP relay |
| `use_tls` | true | STARTTLS on a plain connection (port 587/25) |
| `use_ssl` | false | Implicit TLS from the first byte (port 465) |
| `username` / `password` | — | `${ENV:...}` credentials |
| `from_addr` / `to_addrs` | — | Envelope sender and recipients |

Both TLS modes verify the certificate chain **and** the hostname. If credentials
are configured but neither `use_tls` nor `use_ssl` is on, the channel refuses to
send rather than leak the login over cleartext.

## `database`
`enabled` (true), `path` (`database/webmon.db`), `retention_days` (90; 0 = keep
forever). Old rows are purged periodically by the scheduler.

## `report`
`formats` (`html, json, csv, markdown, pdf`), `directory`, `export_directory`.

## `web`
| Key | Default | Meaning |
|-----|---------|---------|
| `host` / `port` | 127.0.0.1 / 8899 | Bind address |
| `api_token` | `${ENV:WEBMON_API_TOKEN}` | Gates `/api/*`, `/metrics` **and** the dashboard |
| `enable_metrics` | true | Expose Prometheus `/metrics` |

An empty `api_token` leaves the server unauthenticated, which is only safe on
localhost — binding anywhere else without a token is refused at startup. See
[API.md](API.md) for how browsers and scrapers present the token.

## Environment variables

Any `${ENV:NAME}` is replaced by `NAME` at load time and never logged:

```bash
export TELEGRAM_BOT_TOKEN="123:abc"
export TELEGRAM_CHAT_ID="456"
webmon run
```
