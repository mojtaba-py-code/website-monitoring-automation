"""FastAPI dashboard + REST API + Prometheus metrics.

A background task runs monitoring cycles on the default interval and caches the
latest :class:`TargetResult` per target; the dashboard and API read that cache
plus the SQLite history. The API is read-only.

Authentication
--------------
When ``web.api_token`` is set it gates **every** route that exposes monitoring
data -- ``/api/*``, ``/metrics`` and the HTML dashboard -- so nothing leaks when
the server is fronted by a reverse proxy. Tokens are compared in constant time.

* API / metrics clients send ``Authorization: Bearer <token>``.
* Browsers cannot set that header, so ``/`` accepts a ``webmon_session`` cookie
  instead; posting the token to ``/login`` sets it (HttpOnly, SameSite=Strict,
  and Secure whenever the request arrived over HTTPS).

``/api/ping`` stays open on purpose: it is the container health-check and
returns no monitoring data.
"""

from __future__ import annotations

import asyncio
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from ..config import Settings
from ..logger import get_logger
from ..models import TargetResult
from ..monitor import MonitorService

logger = get_logger("web")

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"

_SESSION_COOKIE = "webmon_session"
_SESSION_MAX_AGE = 12 * 3600  # seconds


def _login_page(*, error: str = "") -> str:
    """Minimal sign-in page shown when the dashboard needs the API token.

    ``error`` is a fixed internal string, never user input, so no escaping of
    request data is involved.
    """
    banner = f'<p class="err">{error}</p>' if error else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sign in - Website Monitoring</title>
<style>
 :root {{ color-scheme: dark; }}
 body {{ margin:0; min-height:100vh; display:grid; place-items:center;
        font-family: system-ui,-apple-system,"Segoe UI",sans-serif;
        background:#0d1117; color:#e6edf3; }}
 form {{ background:#161b22; border:1px solid #30363d; border-radius:12px;
        padding:28px 30px; width:min(92vw,340px); }}
 h1 {{ font-size:16px; margin:0 0 4px; }}
 p.sub {{ font-size:12px; color:#8b949e; margin:0 0 18px; }}
 p.err {{ font-size:12px; color:#f85149; margin:0 0 12px; }}
 input {{ width:100%; padding:9px 11px; border-radius:7px; border:1px solid #30363d;
         background:#0d1117; color:#e6edf3; font-size:13px; }}
 button {{ width:100%; margin-top:12px; padding:9px; border:0; border-radius:7px;
          background:#238636; color:#fff; font-size:13px; font-weight:600; cursor:pointer; }}
 button:hover {{ background:#2ea043; }}
</style></head><body>
<form method="post" action="/login">
  <h1>Website Monitoring</h1>
  <p class="sub">This dashboard is protected. Enter the API token to continue.</p>
  {banner}
  <input type="password" name="token" placeholder="API token" autofocus
         autocomplete="current-password" aria-label="API token">
  <button type="submit">Sign in</button>
</form>
</body></html>
"""


def create_app(settings: Settings) -> FastAPI:
    """Build the FastAPI application bound to ``settings``."""
    service = MonitorService(settings, configure_logs=False)
    latest: dict[str, TargetResult] = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> Any:
        async def loop() -> None:
            interval = settings.defaults.interval_seconds
            while True:
                try:
                    for result in await service.run_once():
                        latest[result.target] = result
                except asyncio.CancelledError:
                    raise
                except Exception:  # pragma: no cover - keep the server alive
                    # Never let one bad cycle kill the dashboard, but never fail
                    # silently either: a permanently broken loop must be visible.
                    logger.exception("Background monitoring cycle failed")
                await asyncio.sleep(interval)

        task = asyncio.create_task(loop())
        try:
            yield
        finally:
            task.cancel()
            service.close()

    app = FastAPI(title="Website Monitoring Automation", version="1.0.0", lifespan=lifespan)
    templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))
    if _STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    def _token_matches(candidate: str) -> bool:
        """Constant-time comparison of ``candidate`` against the configured token."""
        token = settings.web.api_token
        if not token:
            return False
        # Compare as bytes so a non-ASCII value can never raise inside compare_digest.
        return secrets.compare_digest(
            candidate.encode("utf-8", "ignore"), token.encode("utf-8")
        )

    def require_token(authorization: str | None = Header(default=None)) -> None:
        """FastAPI dependency gating the machine-readable routes."""
        if not settings.web.api_token:
            return
        header = authorization or ""
        prefix = "Bearer "
        if not (header.startswith(prefix) and _token_matches(header[len(prefix):])):
            raise HTTPException(status_code=401, detail="Invalid or missing API token.")

    def _browser_authorized(request: Request) -> bool:
        """True when the dashboard may be rendered for this request."""
        if not settings.web.api_token:
            return True
        header = request.headers.get("authorization", "")
        prefix = "Bearer "
        if header.startswith(prefix) and _token_matches(header[len(prefix):]):
            return True
        return _token_matches(request.cookies.get(_SESSION_COOKIE, ""))

    # -- dashboard --------------------------------------------------------- #
    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request) -> Any:
        if not _browser_authorized(request):
            return HTMLResponse(_login_page(), status_code=401)
        rows = [latest[k].to_dict() for k in sorted(latest)]
        for row in rows:
            row["availability"] = service.db.availability(row["target"], hours=24)
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "targets": rows,
                "events": service.db.recent_events(limit=15),
                "alerts": service.db.recent_alerts(limit=10),
                "environment": settings.app.environment,
                "summary": {
                    "total": len(rows),
                    "up": sum(1 for r in rows if r["ok"]),
                },
            },
        )

    @app.post("/login")
    async def login(request: Request) -> Any:
        """Exchange the API token for a session cookie so a browser can view ``/``."""
        if not settings.web.api_token:
            return RedirectResponse("/", status_code=303)
        raw = (await request.body())[:4096].decode("utf-8", "ignore")
        submitted = parse_qs(raw).get("token", [""])[0]
        if not _token_matches(submitted):
            return HTMLResponse(_login_page(error="Invalid token."), status_code=401)
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            _SESSION_COOKIE,
            # The configured token, not the submitted string: the two are equal
            # here (constant-time check above), but this keeps request input out
            # of the Set-Cookie header entirely.
            settings.web.api_token,
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
            max_age=_SESSION_MAX_AGE,
            path="/",
        )
        return response

    # -- REST API ---------------------------------------------------------- #
    @app.get("/api/status", dependencies=[Depends(require_token)])
    def api_status() -> dict[str, Any]:
        return {"targets": {k: v.to_dict() for k, v in latest.items()}}

    @app.get("/api/target/{name}", dependencies=[Depends(require_token)])
    def api_target(name: str, hours: int = 24) -> dict[str, Any]:
        if name not in latest and not service.db.availability(name)["samples"]:
            raise HTTPException(status_code=404, detail="Unknown target.")
        return {
            "latest": latest[name].to_dict() if name in latest else None,
            "availability": service.db.availability(name, hours=hours),
            "latency_series": service.db.latency_series(name, hours=hours),
        }

    @app.get("/api/events", dependencies=[Depends(require_token)])
    def api_events(limit: int = 50) -> dict[str, Any]:
        return {"events": service.db.recent_events(limit=limit)}

    @app.get("/api/alerts", dependencies=[Depends(require_token)])
    def api_alerts(limit: int = 50) -> dict[str, Any]:
        return {"alerts": service.db.recent_alerts(limit=limit)}

    @app.get("/api/ping")
    def ping() -> dict[str, str]:
        return {"status": "ok", "service": "website-monitoring-automation"}

    if settings.web.enable_metrics:
        @app.get("/metrics", response_class=PlainTextResponse,
                 dependencies=[Depends(require_token)])
        def metrics() -> str:
            from ..metrics import render_metrics

            return render_metrics(latest, service.db)

    return app


_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def run_server(settings: Settings, *, host: str | None = None, port: int | None = None) -> None:
    """Run the dashboard with uvicorn (blocking).

    Refuses to bind to a non-local interface without an ``api_token`` set, so the
    (unauthenticated) HTML dashboard and metrics cannot be exposed publicly by
    accident. Bind to localhost, or set ``web.api_token`` and front it with a
    TLS-terminating reverse proxy.
    """
    import uvicorn

    bind = host or settings.web.host
    if bind not in _LOCAL_HOSTS and not settings.web.api_token:
        raise RuntimeError(
            f"Refusing to bind the dashboard to {bind!r} without web.api_token set. "
            "Set WEBMON_API_TOKEN (and use a reverse proxy) or bind to 127.0.0.1."
        )
    uvicorn.run(
        create_app(settings),
        host=bind,
        port=port or settings.web.port,
        log_level="info",
    )
