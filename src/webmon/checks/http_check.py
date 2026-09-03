"""HTTP availability probe.

Validates status code, response time, expected/forbidden keywords and reports
security-header hygiene. Redirects are followed safely by ``safe_fetch``.
"""

from __future__ import annotations

from ..config import Target
from ..models import CheckResult, Status
from .base import CheckContext
from .httpclient import safe_fetch

_SECURITY_HEADERS = (
    "strict-transport-security",
    "content-security-policy",
    "x-content-type-options",
    "x-frame-options",
    "referrer-policy",
)


def _security_header_report(headers: dict[str, str]) -> dict[str, bool]:
    return {name: name in headers for name in _SECURITY_HEADERS}


async def check_http(target: Target, ctx: CheckContext) -> CheckResult:
    eff = ctx.effective(target)
    headers = ctx.build_headers(target)
    result = await safe_fetch(target.url, ctx, eff, headers)

    if not result.ok:
        return CheckResult(
            target=target.name,
            kind="http",
            status=Status.DOWN,
            message=result.error or "Request failed",
            details={"redirects": result.redirects},
        )

    details: dict[str, object] = {
        "status_code": result.status_code,
        "response_time_ms": result.latency_ms,
        "response_bytes": len(result.body),
        "truncated": result.truncated,
        "redirects": result.redirects,
        "final_url_changed": result.final_url != target.url,
        "server": result.headers.get("server", ""),
        "security_headers": _security_header_report(result.headers),
    }

    status = Status.UP
    messages: list[str] = []

    if result.status_code not in target.expected_status:
        status = Status.DOWN
        messages.append(f"HTTP {result.status_code} not in {target.expected_status}")

    # Keyword checks operate on the decoded body (best-effort utf-8).
    if status.is_healthy and (target.expected_keywords or target.forbidden_keywords):
        text = result.body.decode("utf-8", errors="replace")
        missing = [kw for kw in target.expected_keywords if kw not in text]
        present = [kw for kw in target.forbidden_keywords if kw in text]
        if missing:
            status = Status.DOWN
            messages.append(f"Missing keyword(s): {', '.join(missing)}")
            details["missing_keywords"] = missing
        if present:
            status = Status.DOWN
            messages.append(f"Forbidden keyword(s) present: {', '.join(present)}")
            details["forbidden_present"] = present

    if (
        status == Status.UP
        and result.latency_ms is not None
        and result.latency_ms > eff.max_response_time_ms
    ):
        status = Status.DEGRADED
        messages.append(f"Slow: {result.latency_ms:.0f}ms > {eff.max_response_time_ms}ms")

    message = "; ".join(messages) or f"HTTP {result.status_code} in {result.latency_ms:.0f}ms"
    return CheckResult(
        target=target.name,
        kind="http",
        status=status,
        latency_ms=result.latency_ms,
        message=message,
        details=details,
    )
