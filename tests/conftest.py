"""Shared pytest fixtures.

Tests never touch the real network: HTTP is mocked with ``respx`` and targets
use loopback IP literals (``127.0.0.1``) with ``block_private_networks`` turned
off so the SSRF guard permits them without any DNS lookup.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from webmon.checks.base import CheckContext
from webmon.config import Settings
from webmon.monitor import MonitorService
from webmon.security import UrlGuard


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """A valid Settings object confined to ``tmp_path`` using loopback targets."""
    data = {
        "app": {"data_dir": ".", "environment": "test"},
        # A high slow-threshold keeps latency-based assertions deterministic even
        # on a loaded CI machine; the DEGRADED path is tested explicitly instead.
        "defaults": {"timeout_seconds": 3, "retries": 0, "interval_seconds": 5,
                     "max_response_time_ms": 30000, "ssl_warning_days": 21},
        "performance": {"max_concurrency": 5, "connect_timeout_seconds": 2},
        "security": {"block_private_networks": False},
        "database": {"enabled": True, "path": "database/test.db"},
        "logging": {"console": False},
        "report": {"formats": ["json", "html"]},
        "targets": [
            {
                "name": "Local Site",
                "url": "http://127.0.0.1/",
                "checks": ["http"],
                "expected_status": [200],
                "expected_keywords": ["OK"],
            }
        ],
        "base_dir": str(tmp_path),
    }
    return Settings.model_validate(data)


@pytest.fixture
def ctx(settings: Settings) -> CheckContext:
    """A CheckContext with the SSRF guard permitting loopback targets."""
    return CheckContext(settings, UrlGuard(settings.security))


@pytest.fixture
def service(settings: Settings) -> Iterator[MonitorService]:
    with MonitorService(settings, configure_logs=False) as svc:
        yield svc
