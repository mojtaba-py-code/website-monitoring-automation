"""Tests for the optional FastAPI web layer (skipped if extras absent)."""

from __future__ import annotations

import httpx
import pytest
import respx

from webmon.config import Settings

pytest.importorskip("fastapi.testclient")
from fastapi.testclient import TestClient

BASE = "http://127.0.0.1/"


def _client(settings: Settings) -> TestClient:
    from webmon.web.server import create_app

    return TestClient(create_app(settings))


@respx.mock
def test_ping_and_dashboard(settings: Settings) -> None:
    respx.get(BASE).mock(return_value=httpx.Response(200, text="OK"))
    with _client(settings) as client:  # triggers lifespan (background loop)
        assert client.get("/api/ping").json()["status"] == "ok"
        assert client.get("/").status_code == 200


@respx.mock
def test_status_and_metrics(settings: Settings) -> None:
    respx.get(BASE).mock(return_value=httpx.Response(200, text="OK"))
    with _client(settings) as client:
        assert client.get("/api/status").status_code == 200
        metrics = client.get("/metrics")
        assert metrics.status_code == 200
        assert "webmon_up" in metrics.text


def test_token_required_when_configured(settings: Settings) -> None:
    settings.web.api_token = "secret-token"
    with _client(settings) as client:
        assert client.get("/api/status").status_code == 401
        ok = client.get("/api/status", headers={"Authorization": "Bearer secret-token"})
        assert ok.status_code == 200


def test_unknown_target_404(settings: Settings) -> None:
    with _client(settings) as client:
        assert client.get("/api/target/does-not-exist").status_code == 404


def test_run_server_refuses_public_bind_without_token(settings: Settings) -> None:
    from webmon.web.server import run_server

    settings.web.api_token = ""
    with pytest.raises(RuntimeError, match="Refusing to bind"):
        run_server(settings, host="0.0.0.0", port=0)


# --------------------------------------------------------------------------- #
# Token gating: with a token configured, nothing that exposes monitoring data
# may be readable without it -- dashboard and /metrics included.
# --------------------------------------------------------------------------- #
def test_dashboard_and_metrics_require_token(settings: Settings) -> None:
    settings.web.api_token = "secret-token"
    with _client(settings) as client:
        page = client.get("/")
        assert page.status_code == 401
        assert "Sign in" in page.text
        assert "Recent status changes" not in page.text  # no data leaked
        assert client.get("/metrics").status_code == 401


def test_metrics_accepts_bearer_token(settings: Settings) -> None:
    settings.web.api_token = "secret-token"
    with _client(settings) as client:
        ok = client.get("/metrics", headers={"Authorization": "Bearer secret-token"})
        assert ok.status_code == 200
        assert "webmon_up" in ok.text


def test_login_sets_session_cookie_and_unlocks_dashboard(settings: Settings) -> None:
    settings.web.api_token = "secret-token"
    with _client(settings) as client:
        posted = client.post("/login", data={"token": "secret-token"}, follow_redirects=False)
        assert posted.status_code == 303
        assert "webmon_session" in posted.cookies
        # The TestClient keeps the cookie, so the dashboard now renders.
        assert client.get("/").status_code == 200


def test_login_rejects_a_wrong_token(settings: Settings) -> None:
    settings.web.api_token = "secret-token"
    with _client(settings) as client:
        bad = client.post("/login", data={"token": "nope"}, follow_redirects=False)
        assert bad.status_code == 401
        assert "webmon_session" not in bad.cookies
        assert client.get("/").status_code == 401


def test_healthcheck_stays_open_with_a_token(settings: Settings) -> None:
    """The container health-check must work without credentials; it leaks nothing."""
    settings.web.api_token = "secret-token"
    with _client(settings) as client:
        assert client.get("/api/ping").status_code == 200


def test_no_token_means_dashboard_is_open(settings: Settings) -> None:
    settings.web.api_token = ""
    with _client(settings) as client:
        assert client.get("/").status_code == 200
        assert client.get("/metrics").status_code == 200
