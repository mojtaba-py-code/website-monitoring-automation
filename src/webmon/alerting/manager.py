"""Alert decision + dispatch.

The :class:`AlertManager` owns two responsibilities:

* **decide** — given a target's new status and its persisted state (consecutive
  failures, last-alert time), decide whether an alert is warranted. This is
  where flap-suppression lives: alert only after ``failure_threshold``
  consecutive failures, re-notify at most every ``renotify_seconds``, and emit a
  recovery notice when a target returns to health.
* **dispatch** — fan the alert out to every enabled channel concurrently.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from ..config import AlertingConfig
from ..logger import get_logger
from ..models import Status
from ..utils import utcnow
from .base import Alert, AlertSeverity, Notifier
from .channels import (
    DiscordNotifier,
    EmailNotifier,
    SlackNotifier,
    TelegramNotifier,
    WebhookNotifier,
)

logger = get_logger("alerting")


def _seconds_since(iso_ts: str | None) -> float:
    if not iso_ts:
        return float("inf")
    try:
        then = datetime.fromisoformat(iso_ts)
    except ValueError:  # pragma: no cover - defensive
        return float("inf")
    return (utcnow() - then).total_seconds()


class AlertManager:
    """Decides on and dispatches alerts across configured channels."""

    def __init__(self, config: AlertingConfig) -> None:
        self._config = config
        self._channels: list[Notifier] = []
        if config.enabled:
            self._build_channels()

    def _build_channels(self) -> None:
        ch = self._config.channels
        if ch.telegram.enabled:
            self._channels.append(TelegramNotifier(ch.telegram))
        if ch.slack.enabled:
            self._channels.append(SlackNotifier(ch.slack))
        if ch.discord.enabled:
            self._channels.append(DiscordNotifier(ch.discord))
        if ch.webhook.enabled:
            self._channels.append(WebhookNotifier(ch.webhook))
        if ch.email.enabled:
            self._channels.append(EmailNotifier(ch.email))

    @property
    def enabled(self) -> bool:
        return self._config.enabled and bool(self._channels)

    @property
    def channel_names(self) -> list[str]:
        return [c.name for c in self._channels]

    def decide(
        self,
        *,
        target: str,
        url: str,
        new_status: Status,
        prev_status: str | None,
        consecutive_failures: int,
        last_alert_ts: str | None,
        detail: str = "",
    ) -> Alert | None:
        """Return an :class:`Alert` to send, or ``None`` to stay quiet."""
        if not self._config.enabled:
            return None
        was_healthy = prev_status is None or Status(prev_status).is_healthy

        if new_status.is_healthy:
            if not was_healthy and self._config.notify_on_recovery:
                return Alert(
                    target=target,
                    severity=AlertSeverity.INFO,
                    title=f"{target} recovered",
                    message=f"{url} is back to {new_status.value.upper()}. {detail}".strip(),
                )
            return None

        if consecutive_failures < self._config.failure_threshold:
            return None

        # Unhealthy and past the failure threshold — throttle re-notifications.
        if last_alert_ts is not None:
            if self._config.renotify_seconds == 0:
                return None
            if _seconds_since(last_alert_ts) < self._config.renotify_seconds:
                return None

        severity = AlertSeverity.CRITICAL if new_status == Status.DOWN else AlertSeverity.WARNING
        return Alert(
            target=target,
            severity=severity,
            title=f"{target} is {new_status.value.upper()}",
            message=f"{url} — {detail}".strip(" —"),
        )

    async def dispatch(self, alert: Alert) -> list[str]:
        """Send ``alert`` to all channels; return the names that succeeded."""
        if not self._channels:
            return []
        results = await asyncio.gather(
            *(self._safe_send(channel, alert) for channel in self._channels)
        )
        return [name for name, ok in results if ok]

    @staticmethod
    async def _safe_send(channel: Notifier, alert: Alert) -> tuple[str, bool]:
        try:
            return channel.name, await channel.send(alert)
        except Exception as exc:  # isolate a misbehaving channel
            logger.warning("Channel %s raised: %s", channel.name, type(exc).__name__)
            return channel.name, False
