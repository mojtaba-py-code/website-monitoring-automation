"""REST/JSON API probe.

Validates the status code, that the body parses as JSON, and any configured
``json_path_checks`` (dotted-path existence / equality). Flags DEGRADED when the
response is slower than the target's threshold.
"""

from __future__ import annotations

import json
from typing import Any

from ..config import JsonPathCheck, Target
from ..models import CheckResult, Status
from .base import CheckContext
from .httpclient import safe_fetch


def _dig(data: Any, path: str) -> tuple[bool, Any]:
    """Follow a dotted path into nested dict/list data. Returns (found, value)."""
    current = data
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return False, None
    return True, current


def _evaluate(check: JsonPathCheck, data: Any) -> str | None:
    """Return an error string if the check fails, else None."""
    found, value = _dig(data, check.path)
    if check.exists and not found:
        return f"JSON path '{check.path}' not found"
    if check.equals is not None and found and value != check.equals:
        return f"JSON path '{check.path}' = {value!r}, expected {check.equals!r}"
    return None


async def check_api(target: Target, ctx: CheckContext) -> CheckResult:
    eff = ctx.effective(target)
    headers = {"Accept": "application/json", **ctx.build_headers(target)}
    result = await safe_fetch(target.url, ctx, eff, headers)

    if not result.ok:
        return CheckResult(target=target.name, kind="api", status=Status.DOWN,
                           message=result.error or "Request failed")

    details: dict[str, object] = {
        "status_code": result.status_code,
        "response_time_ms": result.latency_ms,
    }
    messages: list[str] = []
    status = Status.UP

    if result.status_code not in target.expected_status:
        status = Status.DOWN
        messages.append(f"HTTP {result.status_code} not in {target.expected_status}")

    if status.is_healthy and target.json_path_checks:
        try:
            data = json.loads(result.body.decode("utf-8", errors="replace"))
        except (json.JSONDecodeError, ValueError):
            status = Status.DOWN
            messages.append("Response is not valid JSON")
        else:
            failures = [msg for c in target.json_path_checks if (msg := _evaluate(c, data))]
            if failures:
                status = Status.DOWN
                messages.extend(failures)
                details["json_failures"] = failures

    if (
        status == Status.UP
        and result.latency_ms is not None
        and result.latency_ms > eff.max_response_time_ms
    ):
        status = Status.DEGRADED
        messages.append(f"Slow: {result.latency_ms:.0f}ms")

    message = "; ".join(messages) or f"API OK in {result.latency_ms:.0f}ms"
    return CheckResult(target=target.name, kind="api", status=status,
                       latency_ms=result.latency_ms, message=message, details=details)
