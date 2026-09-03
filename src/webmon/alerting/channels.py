"""Concrete alert channels (async).

Web channels use ``httpx.AsyncClient`` with a short timeout and never raise --
a failed alert must not break the monitoring loop. Crucially, exceptions are
**never** logged verbatim (they can embed secret URLs/tokens); only the error
type or HTTP status is logged. The generic webhook channel HMAC-signs its body
so receivers can verify authenticity.

The e-mail channel always negotiates TLS with a **verified** SSL context
(certificate chain + hostname). ``smtplib`` would otherwise fall back to an
unauthenticated context, leaving the SMTP login open to an active MITM.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import smtplib
import ssl
from email.mime.text import MIMEText

import httpx

from ..config import (
    EmailChannel,
    GenericWebhookChannel,
    TelegramChannel,
    WebhookLikeChannel,
)
from ..logger import get_logger
from .base import Alert, Notifier

logger = get_logger("alerting")
_TIMEOUT = 10.0


async def _post(url: str, *, json_body: dict[str, object] | None = None,
                content: bytes | None = None, headers: dict[str, str] | None = None) -> bool:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(url, json=json_body, content=content, headers=headers)
            response.raise_for_status()
            return True
    except httpx.HTTPStatusError as exc:
        logger.warning("Alert POST failed with HTTP %s", exc.response.status_code)
    except Exception as exc:  # never log the exception text (may contain the URL/secret)
        logger.warning("Alert POST failed: %s", type(exc).__name__)
    return False


class TelegramNotifier(Notifier):
    name = "telegram"

    def __init__(self, config: TelegramChannel) -> None:
        self._config = config

    async def send(self, alert: Alert) -> bool:
        if not (self._config.bot_token and self._config.chat_id):
            return False
        url = f"https://api.telegram.org/bot{self._config.bot_token}/sendMessage"
        return await _post(url, json_body={"chat_id": self._config.chat_id, "text": alert.as_text()})


class SlackNotifier(Notifier):
    name = "slack"

    def __init__(self, config: WebhookLikeChannel) -> None:
        self._config = config

    async def send(self, alert: Alert) -> bool:
        if not self._config.webhook_url:
            return False
        return await _post(self._config.webhook_url, json_body={"text": alert.as_text()})


class DiscordNotifier(Notifier):
    name = "discord"

    def __init__(self, config: WebhookLikeChannel) -> None:
        self._config = config

    async def send(self, alert: Alert) -> bool:
        if not self._config.webhook_url:
            return False
        return await _post(self._config.webhook_url, json_body={"content": alert.as_text()})


class WebhookNotifier(Notifier):
    name = "webhook"

    def __init__(self, config: GenericWebhookChannel) -> None:
        self._config = config

    async def send(self, alert: Alert) -> bool:
        if not self._config.url:
            return False
        payload = json.dumps(
            {
                "target": alert.target,
                "severity": alert.severity.value,
                "title": alert.title,
                "message": alert.message,
            }
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self._config.secret:
            signature = hmac.new(
                self._config.secret.encode("utf-8"), payload, hashlib.sha256
            ).hexdigest()
            headers["X-Webhook-Signature"] = f"sha256={signature}"
        return await _post(self._config.url, content=payload, headers=headers)


class EmailNotifier(Notifier):
    name = "email"

    def __init__(self, config: EmailChannel) -> None:
        self._config = config

    async def send(self, alert: Alert) -> bool:
        import asyncio

        return await asyncio.to_thread(self._send_blocking, alert)

    def _send_blocking(self, alert: Alert) -> bool:
        cfg = self._config
        if not (cfg.smtp_host and cfg.from_addr and cfg.to_addrs):
            return False
        message = MIMEText(alert.message, _charset="utf-8")
        message["Subject"] = f"[{alert.severity.value.upper()}] {alert.title}"
        message["From"] = cfg.from_addr
        message["To"] = ", ".join(cfg.to_addrs)
        # Verifies the certificate chain AND the hostname. Passing this
        # explicitly matters: smtplib's default STARTTLS context does neither.
        context = ssl.create_default_context()
        try:
            server: smtplib.SMTP
            if cfg.use_ssl:
                # Implicit TLS (SMTPS, usually port 465) -- encrypted from the
                # first byte, so there is no cleartext window to strip.
                server = smtplib.SMTP_SSL(
                    cfg.smtp_host, cfg.smtp_port, timeout=_TIMEOUT, context=context
                )
            else:
                server = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=_TIMEOUT)
            with server:
                if cfg.use_tls and not cfg.use_ssl:
                    server.starttls(context=context)
                if cfg.username and cfg.password:
                    # Refuse to hand credentials to an unencrypted session.
                    if not (cfg.use_ssl or cfg.use_tls):
                        logger.warning(
                            "Email alert skipped: refusing to send SMTP credentials "
                            "over an unencrypted connection (enable use_tls or use_ssl)."
                        )
                        return False
                    server.login(cfg.username, cfg.password)
                server.sendmail(cfg.from_addr, cfg.to_addrs, message.as_string())
            return True
        except (OSError, smtplib.SMTPException) as exc:
            logger.warning("Email alert failed: %s", type(exc).__name__)
            return False
