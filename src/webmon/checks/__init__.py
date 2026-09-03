"""Monitoring probes.

Each probe is an async callable ``(target, ctx) -> CheckResult``. The registry
below maps a check *kind* (as configured on a target) to its implementation so
the monitor can run exactly the checks a target asks for.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from ..config import Target
from ..models import CheckResult
from .api_check import check_api
from .base import CheckContext
from .content_check import check_content
from .dns_check import check_dns
from .http_check import check_http
from .ping_check import check_ping
from .port_check import check_port
from .ssl_check import check_ssl

CheckFn = Callable[[Target, CheckContext], Awaitable[CheckResult]]

REGISTRY: dict[str, CheckFn] = {
    "http": check_http,
    "api": check_api,
    "ssl": check_ssl,
    "dns": check_dns,
    "ping": check_ping,
    "port": check_port,
    "content": check_content,
}

__all__ = ["REGISTRY", "CheckContext", "CheckFn"]
