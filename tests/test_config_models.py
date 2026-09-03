"""Tests for configuration loading and domain models."""

from __future__ import annotations

from pathlib import Path

import pytest

from webmon.config import ConfigError, Settings, load_settings
from webmon.models import CheckResult, Status, TargetResult, worst


def test_defaults_build() -> None:
    settings = load_settings(None)
    assert settings.defaults.timeout_seconds == 10.0
    assert settings.security.block_private_networks is True


def test_env_placeholder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TG_TOKEN", "secret123")
    cfg = tmp_path / "config" / "config.yaml"
    cfg.parent.mkdir()
    cfg.write_text(
        "alerting:\n  channels:\n    telegram:\n      bot_token: '${ENV:TG_TOKEN}'\n",
        encoding="utf-8",
    )
    settings = load_settings(cfg)
    assert settings.alerting.channels.telegram.bot_token == "secret123"
    assert settings.base_dir == tmp_path.resolve()


def test_invalid_config_raises(tmp_path: Path) -> None:
    cfg = tmp_path / "bad.yaml"
    cfg.write_text("defaults:\n  timeout_seconds: -5\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings(cfg)


def test_target_slug() -> None:
    settings = Settings.model_validate({"targets": [{"name": "My Site!", "url": "https://x.com"}]})
    assert settings.targets[0].slug == "my-site"


def test_enabled_targets_filter() -> None:
    settings = Settings.model_validate(
        {"targets": [
            {"name": "a", "url": "https://a.com", "enabled": True},
            {"name": "b", "url": "https://b.com", "enabled": False},
        ]}
    )
    assert [t.name for t in settings.enabled_targets()] == ["a"]


def test_worst_status() -> None:
    assert worst([Status.UP, Status.DOWN, Status.WARNING]) == Status.DOWN
    assert worst([Status.UP, Status.WARNING]) == Status.WARNING
    assert worst([]) == Status.UNKNOWN


def test_status_health() -> None:
    assert Status.UP.is_healthy
    assert Status.WARNING.is_healthy
    assert not Status.DOWN.is_healthy
    assert not Status.DEGRADED.is_healthy


def test_target_result_aggregation() -> None:
    checks = [
        CheckResult("t", "http", Status.UP, latency_ms=120.0),
        CheckResult("t", "ssl", Status.WARNING),
    ]
    result = TargetResult.from_checks("t", "https://t.com", checks)
    assert result.status == Status.WARNING
    assert result.response_time_ms == 120.0
    assert result.to_dict()["ok"] is True
