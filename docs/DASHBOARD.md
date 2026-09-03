# Dashboard Guide

```bash
pip install -e ".[web]"
webmon dashboard --host 127.0.0.1 --port 8899
```

Open <http://127.0.0.1:8899>.

## What it shows

* **Summary cards** — total targets, how many are up, how many down/degraded.
* **Targets table** — per-target status pill, URL, last response time, 24h
  availability, and per-check status (`http:up`, `ssl:warning`, …).
* **Recent status changes** — the up/down timeline from the events table.
* **Recent alerts** — what was raised and to which channels.

A background task runs monitoring cycles on `defaults.interval_seconds` and the
page auto-refreshes every 20 seconds.

## Security

* Binds to `127.0.0.1` by default, and **refuses to start** on any other
  interface unless `web.api_token` is set.
* With a token set, nothing that exposes monitoring data is readable without it
  — `/api/*`, `/metrics` and the dashboard itself. Visiting `/` then shows a
  sign-in page; submitting the token stores it in a `webmon_session` cookie
  (HttpOnly, SameSite=Strict, Secure over HTTPS) for 12 hours.
* The dashboard and API are read-only; there is no control surface to mutate
  monitoring state from the browser.
* Still put a TLS-terminating reverse proxy in front before exposing it — the
  token travels in a header/cookie and deserves an encrypted channel.

## Behind a reverse proxy (nginx)

```nginx
location / {
    proxy_pass http://127.0.0.1:8899;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $remote_addr;
}
```

Terminate TLS at the proxy and set `web.api_token` so every route stays
protected even if the port becomes reachable. Layering your own SSO or HTTP
Basic auth on top is fine — the token check is independent of it.

## Grafana

Point Grafana at Prometheus scraping `/metrics` (see [API.md](API.md)) and build
panels on `webmon_up`, `webmon_response_time_ms` and `webmon_availability_ratio`.
