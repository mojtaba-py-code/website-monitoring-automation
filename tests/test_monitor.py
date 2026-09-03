"""Integration tests for the monitor orchestrator (HTTP mocked)."""

from __future__ import annotations

import httpx
import pytest
import respx

from webmon.config import Settings
from webmon.models import Status
from webmon.monitor import MonitorService

pytestmark = pytest.mark.integration

BASE = "http://127.0.0.1/"


@respx.mock
async def test_run_once_healthy(service: MonitorService) -> None:
    respx.get(BASE).mock(return_value=httpx.Response(200, text="OK"))
    results = await service.run_once()
    assert len(results) == 1
    assert results[0].status == Status.UP
    # Persisted to history.
    assert service.db.availability("Local Site")["samples"] == 1


@respx.mock
async def test_state_transition_records_event(service: MonitorService) -> None:
    respx.get(BASE).mock(return_value=httpx.Response(200, text="OK"))
    await service.run_once()
    respx.get(BASE).mock(return_value=httpx.Response(500, text="boom"))
    await service.run_once()
    events = service.db.recent_events()
    assert any(e["to_status"] == "down" for e in events)


@respx.mock
async def test_consecutive_failures_increment(service: MonitorService) -> None:
    respx.get(BASE).mock(return_value=httpx.Response(500))
    await service.run_once()
    await service.run_once()
    state = service.db.get_state("Local Site")
    assert state["consecutive_failures"] == 2


@respx.mock
async def test_content_change_detection(tmp_path, settings: Settings) -> None:
    settings.targets[0].checks = ["content"]  # type: ignore[list-item]
    settings.targets[0].content_hash_check = True
    with MonitorService(settings, configure_logs=False) as service:
        respx.get(BASE).mock(return_value=httpx.Response(200, text="version 1"))
        await service.run_once()
        respx.get(BASE).mock(return_value=httpx.Response(200, text="version 2 changed"))
        results = await service.run_once()
        # Second cycle should flag a content change as a WARNING.
        assert results[0].status == Status.WARNING
        assert any(c.kind == "change" for c in results[0].checks)
