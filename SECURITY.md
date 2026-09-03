# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 1.0.x   | ✅ |

## Reporting a vulnerability

**Please do not open a public issue for a security problem.**

Report it privately through
[GitHub Security Advisories](https://github.com/mojtaba-py-code/website-monitoring-automation/security/advisories/new),
which opens a channel visible only to the maintainers.

Please include:

* what the issue is and which component it affects,
* the steps or a minimal config that reproduces it,
* the impact you believe it has,
* the version / commit you tested.

You can expect an acknowledgement within **72 hours** and an assessment within
**7 days**. Fixes are released as a patch version, and reporters are credited in
the changelog unless they ask otherwise.

## Threat model

This tool makes outbound network requests to hosts named in the operator's own
configuration file. The config is trusted input; the *responses* are not.
The controls below reflect that boundary.

### What the project defends against

| Risk | Control |
|------|---------|
| SSRF via target or redirect URLs | `UrlGuard` validates scheme, host block/allow-lists and resolved IPs before every connection; the block-list also matches resolved addresses |
| Open-redirect pivot to internal services | Redirects are followed **manually** and every hop is re-validated; `169.254.169.254` is block-listed by default |
| Credential leakage across hosts | `Authorization` and `Cookie` headers are dropped on a cross-host redirect |
| Secrets in logs | Secrets are referenced as `${ENV:VAR}`; `redact()` masks tokens, passwords, URL user-info and sensitive query parameters; `redact_headers()` matches on the header *name* so an operator-chosen `api_key_header` is masked too; failed alert deliveries log only a status code or exception type |
| Memory exhaustion from hostile responses | Response bodies are read with a hard byte cap |
| SMTP credential interception | The e-mail channel supplies its own SSL context (chain **and** hostname verified) and refuses to authenticate over an unencrypted session |
| Unauthenticated exposure of monitoring data | `web.api_token` gates `/api/*`, `/metrics` and the dashboard; the server refuses a non-localhost bind without one |
| Timing attacks on the API token | Compared with `secrets.compare_digest` |
| A stolen dashboard cookie driving the API | The cookie carries an HMAC derived from the token, never the token; it is HttpOnly, SameSite=Strict, and Secure over HTTPS |
| Command injection via the ICMP probe | `ping` is executed with a fixed argument vector (never a shell) and the host is validated against an option-injection allow-list |
| SQL injection | All values are bound parameters; the few interpolated table names are checked against an allow-list |

### Known limitations

* **DNS rebinding.** The guard resolves and checks a target's addresses, but the
  HTTP client resolves the name again when it connects. A hostile low-TTL domain
  could in principle change its answer in between. Targets come from the
  operator's own config rather than untrusted runtime input, which makes this
  impractical; keep `block_private_networks: true` in production.
* **The HTML dashboard is read-only but not audited for multi-tenant use.** It
  is intended for an operator, behind a token and a TLS-terminating proxy — not
  as a public status page.
* **`allowlist_hosts` fully bypasses the private-network block** for the hosts
  it names. That is its purpose; add entries deliberately.
* **Alert channel URLs are not SSRF-checked.** They are operator-supplied
  destinations, treated as trusted config like the SMTP host.

## Operating it safely

* Keep `security.block_private_networks: true` unless you are deliberately
  monitoring an internal network you own.
* Never commit `config/config.yaml` or `.env` — both are git-ignored. Reference
  every secret as `${ENV:VAR}`.
* Set `web.api_token` and front the dashboard with a TLS-terminating reverse
  proxy before exposing it anywhere but localhost.
* Set `database.retention_days` so monitoring history does not grow unbounded.
