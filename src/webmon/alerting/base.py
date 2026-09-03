"""Alert value object and the channel interface."""

from __future__ import annotations

import abc
from dataclasses import dataclass
from enum import Enum


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(slots=True)
class Alert:
    """A single alert to deliver across one or more channels."""

    target: str
    severity: AlertSeverity
    title: str
    message: str

    def as_text(self) -> str:
        return f"[{self.severity.value.upper()}] {self.title}\n{self.message}"


class Notifier(abc.ABC):
    """Base class for one delivery channel."""

    name: str = "notifier"

    @abc.abstractmethod
    async def send(self, alert: Alert) -> bool:
        """Deliver ``alert``; return True on success. Must never raise."""
        raise NotImplementedError
