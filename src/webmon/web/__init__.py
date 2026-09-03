"""Optional FastAPI dashboard, REST API and Prometheus metrics.

Imported only when the ``web`` extra is installed; nothing in the core package
imports it eagerly.
"""

from __future__ import annotations

__all__ = ["server"]
