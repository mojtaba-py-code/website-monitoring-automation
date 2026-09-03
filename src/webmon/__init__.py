"""Website Monitoring Automation.

An asynchronous, production-grade monitoring platform that continuously checks
websites, APIs, SSL certificates, DNS records, TCP ports and network reachability,
then records history, raises alerts and produces reports and a live dashboard.

The package follows a clean, layered design:

* :mod:`webmon.config`      -- typed, validated configuration (pydantic)
* :mod:`webmon.security`    -- URL validation & SSRF guard, secret redaction
* :mod:`webmon.checks`      -- one probe per concern (http/ssl/dns/port/ping/...)
* :mod:`webmon.monitor`     -- async orchestrator that runs checks concurrently
* :mod:`webmon.database`    -- SQLite history / metrics store (repository pattern)
* :mod:`webmon.alerting`   -- multi-channel alerts with flap-suppression
* :mod:`webmon.reports`     -- HTML/JSON/CSV/Markdown/PDF reporting
* :mod:`webmon.scheduler`   -- periodic execution loop
* :mod:`webmon.cli`         -- command-line interface
* :mod:`webmon.web`         -- FastAPI dashboard + REST API + Prometheus metrics
"""

from __future__ import annotations

__all__ = ["__author__", "__version__"]

__version__ = "1.0.0"
__author__ = "Mojtaba Karimi"
