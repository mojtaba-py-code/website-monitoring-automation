# REST API & Metrics

Start with `webmon dashboard` (requires the `web` extra). The API is **read-only**.

## Authentication

If `web.api_token` is set (required for any non-localhost bind), it gates
**every route that exposes monitoring data** — `/api/*`, `/metrics` and the HTML
dashboard. Machine clients send:

```
Authorization: Bearer <token>
```

The token is compared in constant time.

Browsers cannot set that header, so the dashboard at `/` also accepts a
`webmon_session` cookie. `POST /login` with a `token` form field exchanges the
token for one (HttpOnly, SameSite=Strict, and Secure whenever the request
arrived over HTTPS, so it is safe behind a TLS-terminating proxy).

`/api/ping` is the only unauthenticated route — it is the container health
probe and returns no monitoring data.

### Scraping `/metrics` with a token

```yaml
scrape_configs:
  - job_name: webmon
    authorization:
      credentials: "<your WEBMON_API_TOKEN>"
    static_configs:
      - targets: ["127.0.0.1:8899"]
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | HTML dashboard (token via `webmon_session` cookie) |
| POST | `/login` | Exchange the token for a dashboard session cookie |
| GET | `/api/ping` | Liveness probe → `{"status":"ok"}` — always open |
| GET | `/api/status` | Latest result for every target |
| GET | `/api/target/{name}?hours=24` | Latest result + availability + latency series |
| GET | `/api/events?limit=50` | Recent status-change events |
| GET | `/api/alerts?limit=50` | Recent alerts |
| GET | `/metrics` | Prometheus text exposition |

Every route except `/api/ping` requires the token when one is configured.

## Examples

```bash
curl -s http://127.0.0.1:8899/api/status | jq
curl -s -H "Authorization: Bearer $WEBMON_API_TOKEN" \
     http://127.0.0.1:8899/api/target/Example%20Website | jq
```

### Sample `/api/status`

```json
{
  "targets": {
    "Example Website": {
      "target": "Example Website",
      "url": "https://example.com",
      "status": "up",
      "ok": true,
      "response_time_ms": 142.5,
      "checks": [{ "kind": "http", "status": "up", "latency_ms": 142.5 }]
    }
  }
}
```

## Prometheus metrics

```
# TYPE webmon_up gauge
webmon_up{target="Example Website"} 1
# TYPE webmon_response_time_ms gauge
webmon_response_time_ms{target="Example Website"} 142.5
# TYPE webmon_availability_ratio gauge
webmon_availability_ratio{target="Example Website"} 0.99861
```

Scrape config:

```yaml
scrape_configs:
  - job_name: webmon
    static_configs:
      - targets: ["127.0.0.1:8899"]
```

## Webhook alerts (receiver side)

The generic webhook channel POSTs JSON and, if a secret is configured, signs the
body:

```
X-Webhook-Signature: sha256=<hmac-sha256(secret, body)>
```

Verify it on your receiver before trusting the payload.
