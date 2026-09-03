"""Tests for the argparse CLI."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from webmon.cli import build_parser, main

BASE = "http://127.0.0.1/"


@pytest.fixture
def cli_config(tmp_path: Path) -> str:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "logging:\n  console: false\n"
        "security:\n  block_private_networks: false\n"
        "database:\n  path: 'database/cli.db'\n"
        "targets:\n"
        "  - name: 'Loopback'\n"
        "    url: 'http://127.0.0.1/'\n"
        "    checks: ['http']\n"
        "    expected_status: [200]\n",
        encoding="utf-8",
    )
    return str(cfg)


def _base(cfg: str, tmp_path: Path) -> list[str]:
    return ["--config", cfg, "--data-dir", str(tmp_path), "--silent"]


def test_parser_requires_command() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_version() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0


def test_list_command(cli_config: str, tmp_path: Path) -> None:
    assert main([*_base(cli_config, tmp_path), "list"]) == 0


@respx.mock
def test_check_healthy(cli_config: str, tmp_path: Path) -> None:
    respx.get(BASE).mock(return_value=httpx.Response(200, text="OK"))
    assert main([*_base(cli_config, tmp_path), "check"]) == 0


@respx.mock
def test_check_unhealthy_exit_code(cli_config: str, tmp_path: Path) -> None:
    respx.get(BASE).mock(return_value=httpx.Response(500))
    assert main([*_base(cli_config, tmp_path), "check"]) == 3


@respx.mock
def test_report_command_writes_files(cli_config: str, tmp_path: Path) -> None:
    respx.get(BASE).mock(return_value=httpx.Response(200, text="OK"))
    assert main([*_base(cli_config, tmp_path), "--json", "report"]) == 0
    assert list((tmp_path / "reports").glob("*.json"))


def test_schedule_command(cli_config: str, tmp_path: Path) -> None:
    assert main([*_base(cli_config, tmp_path), "schedule"]) == 0


@respx.mock
def test_dns_adhoc(cli_config: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from webmon.checks import dns_check

    monkeypatch.setattr(dns_check, "_resolve_records", lambda *a: {"A": ["1.2.3.4"]})
    assert main([*_base(cli_config, tmp_path), "dns", "https://example.test/"]) == 0


def test_bad_config_returns_one(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("defaults:\n  timeout_seconds: -1\n", encoding="utf-8")
    assert main(["--config", str(bad), "--silent", "list"]) == 1
