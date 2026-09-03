"""Content-integrity probe.

Fetches the page body and computes a SHA-256 checksum plus lightweight HTML
metrics (size, title). The probe itself is stateless and reports the current
checksum; the monitor compares it against the previously stored checksum to
detect *content changes* over time (raising a WARNING when it differs).
"""

from __future__ import annotations

import hashlib
import re

from ..config import Target
from ..models import CheckResult, Status
from .base import CheckContext
from .httpclient import safe_fetch

_TITLE_RE = re.compile(rb"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


async def check_content(target: Target, ctx: CheckContext) -> CheckResult:
    eff = ctx.effective(target)
    headers = ctx.build_headers(target)
    result = await safe_fetch(target.url, ctx, eff, headers)

    if not result.ok or result.status_code is None:
        return CheckResult(
            target=target.name, kind="content", status=Status.DOWN,
            message=result.error or "Fetch failed",
        )

    checksum = hashlib.sha256(result.body).hexdigest()
    title_match = _TITLE_RE.search(result.body)
    title = title_match.group(1).decode("utf-8", errors="replace").strip() if title_match else ""
    details = {
        "checksum": checksum,
        "content_bytes": len(result.body),
        "title": title[:200],
        "hash_tracking": target.content_hash_check,
    }
    return CheckResult(
        target=target.name, kind="content", status=Status.UP,
        message=f"Checksum {checksum[:12]}… ({len(result.body)} bytes)", details=details,
    )
