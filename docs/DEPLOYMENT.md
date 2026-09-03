# Deployment Guide

## Local / bare metal

```bash
pip install -e ".[web,pdf]"
cp config/config.example.yaml config/config.yaml   # edit targets & secrets
export TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=...  # if using alerts
webmon run          # continuous monitoring
webmon dashboard    # (separately) the dashboard
```

## systemd (Linux)

`/etc/systemd/system/webmon.service`:

```ini
[Unit]
Description=Website Monitoring Automation
After=network-online.target

[Service]
WorkingDirectory=/opt/webmon
Environment=TELEGRAM_BOT_TOKEN=...
Environment=TELEGRAM_CHAT_ID=...
ExecStart=/opt/webmon/.venv/bin/webmon run
Restart=on-failure
User=webmon

[Install]
WantedBy=multi-user.target
```

```bash
systemctl enable --now webmon
```

## Cron / Task Scheduler (one-shot cycles)

```bash
webmon schedule     # prints ready-to-use cron + schtasks lines
# e.g. cron: */5 * * * * /opt/webmon/.venv/bin/webmon check
```

## Docker

```bash
docker compose -f deploy/docker-compose.yml up --build -d
```

The compose file runs two services from the same image: the continuous monitor
(`webmon run`) and the dashboard (`webmon dashboard`), sharing a named volume so
history persists. Provide secrets via an `.env` file (never bake them into the
image):

```env
TELEGRAM_BOT_TOKEN=123:abc
TELEGRAM_CHAT_ID=456
WEBMON_API_TOKEN=change-me
```

> `WEBMON_API_TOKEN` is **required** for the dashboard service: it binds to
> `0.0.0.0` inside the container, and the server refuses a non-local bind
> without a token. Generate one with
> `python -c "import secrets; print(secrets.token_urlsafe(32))"`. The published
> port is mapped to `127.0.0.1` only, so put a TLS-terminating reverse proxy in
> front before exposing it beyond the host.

### Standalone container

```bash
docker build -f deploy/Dockerfile -t webmon .
docker run --rm -v webmon-data:/data \
  -v $(pwd)/config:/app/config:ro \
  --env-file .env webmon webmon run
```

## Kubernetes (sketch)

Run the monitor as a `Deployment`, mount the config from a `ConfigMap`, inject
secrets from a `Secret`, and expose the dashboard via a `Service`. Scrape
`/metrics` with a `ServiceMonitor` (Prometheus Operator).

## Operational notes

* **Persistence** — mount `database/`, `reports/`, `exports/`, `logs/` (or set
  `app.data_dir` to a mounted path).
* **Retention** — tune `database.retention_days` to bound the DB size.
* **Secrets** — always via environment variables / secret stores, never in the
  committed config. `config/config.yaml` is git-ignored.
* **Exposure** — bind the dashboard to localhost or protect it with a token and
  reverse proxy; keep `security.block_private_networks: true` in production.
* **Scraping** — when a token is set, `/metrics` needs it too; give Prometheus
  an `authorization.credentials` entry (see [API.md](API.md)).
