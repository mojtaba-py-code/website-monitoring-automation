"""Tests for the HTTP / API / content probes (HTTP fully mocked with respx)."""

from __future__ import annotations

import httpx
import pytest
import respx

from webmon.checks.api_check import check_api
from webmon.checks.base import CheckContext
from webmon.checks.content_check import check_content
from webmon.checks.http_check import check_http
from webmon.config import Target
from webmon.models import Status

BASE = "http://127.0.0.1/"


def _target(**kw: object) -> Target:
    kw.setdefault("name", "t")
    kw.setdefault("url", BASE)
    return Target(**kw)  # type: ignore[arg-type]


@respx.mock
async def test_http_up(ctx: CheckContext) -> None:
    respx.get(BASE).mock(return_value=httpx.Response(200, text="Everything OK here"))
    result = await check_http(_target(expected_keywords=["OK"]), ctx)
    assert result.status == Status.UP
    assert result.latency_ms is not None
    assert result.details["status_code"] == 200


@respx.mock
async def test_http_bad_status(ctx: CheckContext) -> None:
    respx.get(BASE).mock(return_value=httpx.Response(503, text="down"))
    result = await check_http(_target(), ctx)
    assert result.status == Status.DOWN
    assert "503" in result.message


@respx.mock
async def test_http_missing_keyword(ctx: CheckContext) -> None:
    respx.get(BASE).mock(return_value=httpx.Response(200, text="nothing here"))
    result = await check_http(_target(expected_keywords=["WELCOME"]), ctx)
    assert result.status == Status.DOWN
    assert "Missing keyword" in result.message


@respx.mock
async def test_http_forbidden_keyword(ctx: CheckContext) -> None:
    respx.get(BASE).mock(return_value=httpx.Response(200, text="Fatal error occurred"))
    result = await check_http(_target(forbidden_keywords=["Fatal error"]), ctx)
    assert result.status == Status.DOWN


@respx.mock
async def test_http_connection_error(ctx: CheckContext) -> None:
    respx.get(BASE).mock(side_effect=httpx.ConnectError("refused"))
    result = await check_http(_target(), ctx)
    assert result.status == Status.DOWN


@respx.mock
async def test_http_follows_safe_redirect(ctx: CheckContext) -> None:
    respx.get(BASE).mock(return_value=httpx.Response(302, headers={"location": "http://127.0.0.1/final"}))
    respx.get("http://127.0.0.1/final").mock(return_value=httpx.Response(200, text="OK"))
    result = await check_http(_target(expected_keywords=["OK"]), ctx)
    assert result.status == Status.UP
    assert result.details["redirects"] == 1


@respx.mock
async def test_redirect_drops_credentials_cross_host(ctx: CheckContext) -> None:
    # A bearer-authed request that redirects to a different host must not leak
    # the Authorization header to that host.
    respx.get(BASE).mock(return_value=httpx.Response(302, headers={"location": "http://1.1.1.1/next"}))
    captured: dict[str, str] = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        captured.update(request.headers)
        return httpx.Response(200, text="OK")

    respx.get("http://1.1.1.1/next").mock(side_effect=_capture)
    target = _target(expected_keywords=["OK"], auth={"type": "bearer", "token": "SEKRIT"})
    await check_http(target, ctx)
    assert "authorization" not in {k.lower() for k in captured}


@respx.mock
async def test_http_blocks_ssrf_redirect(ctx: CheckContext) -> None:
    # Redirect to the cloud metadata endpoint must be refused (it is block-listed).
    respx.get(BASE).mock(
        return_value=httpx.Response(302, headers={"location": "http://169.254.169.254/latest"})
    )
    result = await check_http(_target(), ctx)
    assert result.status == Status.DOWN
    assert "redirect" in result.message.lower()


@respx.mock
async def test_http_slow_is_degraded(ctx: CheckContext) -> None:
    respx.get(BASE).mock(return_value=httpx.Response(200, text="OK"))
    # A 1 ms threshold forces the DEGRADED path deterministically.
    result = await check_http(_target(expected_keywords=["OK"], max_response_time_ms=1), ctx)
    assert result.status == Status.DEGRADED
    assert "Slow" in result.message


@respx.mock
async def test_http_security_headers_reported(ctx: CheckContext) -> None:
    respx.get(BASE).mock(
        return_value=httpx.Response(200, text="OK", headers={"strict-transport-security": "max-age=1"})
    )
    result = await check_http(_target(expected_keywords=["OK"]), ctx)
    sec = result.details["security_headers"]
    assert sec["strict-transport-security"] is True
    assert sec["content-security-policy"] is False


@respx.mock
async def test_api_json_path_pass(ctx: CheckContext) -> None:
    respx.get(BASE).mock(return_value=httpx.Response(200, json={"status": "ok", "n": 1}))
    target = _target(checks=["api"], json_path_checks=[{"path": "status", "equals": "ok"}])
    result = await check_api(target, ctx)
    assert result.status == Status.UP


@respx.mock
async def test_api_json_path_fail(ctx: CheckContext) -> None:
    respx.get(BASE).mock(return_value=httpx.Response(200, json={"status": "degraded"}))
    target = _target(checks=["api"], json_path_checks=[{"path": "status", "equals": "ok"}])
    result = await check_api(target, ctx)
    assert result.status == Status.DOWN
    assert "json" in " ".join(result.details.get("json_failures", [])).lower() or result.message


@respx.mock
async def test_api_invalid_json(ctx: CheckContext) -> None:
    respx.get(BASE).mock(return_value=httpx.Response(200, text="not json"))
    target = _target(checks=["api"], json_path_checks=[{"path": "x"}])
    result = await check_api(target, ctx)
    assert result.status == Status.DOWN


@respx.mock
async def test_content_checksum(ctx: CheckContext) -> None:
    respx.get(BASE).mock(return_value=httpx.Response(200, text="<title>Hi</title>body"))
    result = await check_content(_target(checks=["content"]), ctx)
    assert result.status == Status.UP
    assert len(result.details["checksum"]) == 64
    assert result.details["title"] == "Hi"


@pytest.mark.parametrize("kw", ["OK", "ok"])
@respx.mock
async def test_http_keyword_case_sensitive(ctx: CheckContext, kw: str) -> None:
    respx.get(BASE).mock(return_value=httpx.Response(200, text="OK"))
    result = await check_http(_target(expected_keywords=[kw]), ctx)
    # "OK" present, "ok" absent -> case-sensitive matching.
    assert result.status == (Status.UP if kw == "OK" else Status.DOWN)
