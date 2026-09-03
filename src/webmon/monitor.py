"""Async monitoring orchestrator.

``MonitorService`` runs the configured checks for each target concurrently
(bounded by a semaphore), aggregates them into a :class:`TargetResult`,
persists everything, detects state transitions and DNS/content changes, and
drives alerting with flap-suppression.

It is the single seam shared by the CLI, the scheduler and the web API.
"""

from __future__ import annotations

import asyncio

from .alerting import AlertManager
from .checks import REGISTRY, CheckContext
from .config import Settings, Target
from .database import DatabaseLike, open_database
from .logger import audit, configure_logging, get_logger
from .models import CheckResult, Status, TargetResult
from .security import UrlGuard
from .utils import iso_now

logger = get_logger("monitor")


class MonitorService:
    """Runs monitoring cycles and processes their results."""

    def __init__(self, settings: Settings, *, configure_logs: bool = True, silent: bool = False) -> None:
        self.settings = settings
        settings.ensure_directories()
        if configure_logs:
            configure_logging(settings.logging, settings.log_dir, silent=silent)
        self.guard = UrlGuard(settings.security)
        self.ctx = CheckContext(settings, self.guard)
        self.db: DatabaseLike = open_database(settings.database_path, enabled=settings.database.enabled)
        self.alerts = AlertManager(settings.alerting)
        self._semaphore = asyncio.Semaphore(settings.performance.max_concurrency)

    # -- lifecycle --------------------------------------------------------- #
    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> MonitorService:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- single target ----------------------------------------------------- #
    async def check_target(self, target: Target) -> TargetResult:
        """Run all of a target's configured checks concurrently."""
        kinds = [k for k in target.checks if k in REGISTRY]

        async def _run(kind: str) -> CheckResult:
            async with self._semaphore:
                try:
                    return await REGISTRY[kind](target, self.ctx)
                except Exception as exc:  # a check must never crash the cycle
                    logger.exception("Check %s for %s failed", kind, target.name)
                    return CheckResult(
                        target=target.name, kind=kind, status=Status.DOWN,
                        message=f"Check error: {type(exc).__name__}",
                    )

        checks = await asyncio.gather(*(_run(kind) for kind in kinds)) if kinds else []
        return TargetResult.from_checks(target.name, target.url, list(checks))

    # -- processing / persistence / alerting ------------------------------- #
    async def process(self, target: Target, result: TargetResult) -> TargetResult:
        state = self.db.get_state(target.name)
        prev_status = state.get("last_status")

        result = self._apply_change_detection(target, result, state)

        # Persist the results.
        self.db.record_result(result)
        for check in result.checks:
            self.db.record_check(check)

        # State-transition event.
        if prev_status != result.status.value:
            self.db.record_event(target.name, prev_status, result.status.value, self._summary(result))
            audit("status-change", target=target.name, **{"from": prev_status or "new", "to": result.status.value})

        # Consecutive-failure counter for flap suppression.
        failures = int(state.get("consecutive_failures", 0))
        failures = 0 if result.ok else failures + 1

        # Alert decision + dispatch.
        last_alert_ts = state.get("last_alert_ts")
        if self.alerts.enabled:
            alert = self.alerts.decide(
                target=target.name, url=target.url, new_status=result.status,
                prev_status=prev_status, consecutive_failures=failures,
                last_alert_ts=last_alert_ts, detail=self._summary(result),
            )
            if alert is not None:
                sent = await self.alerts.dispatch(alert)
                self.db.record_alert(target.name, alert.severity.value, alert.title, alert.message, sent)
                audit("alert", target=target.name, severity=alert.severity.value, channels=",".join(sent) or "none")
                last_alert_ts = None if result.ok else iso_now()

        # Persist updated state (incl. change-detection fingerprints).
        self.db.update_state(
            target.name,
            last_status=result.status.value,
            last_change_ts=iso_now() if prev_status != result.status.value else state.get("last_change_ts"),
            consecutive_failures=failures,
            last_alert_ts=last_alert_ts,
            dns_fingerprint=self._extract(result, "dns", "fingerprint") or state.get("dns_fingerprint"),
            content_checksum=self._extract(result, "content", "checksum") or state.get("content_checksum"),
        )
        return result

    def _apply_change_detection(self, target: Target, result: TargetResult, state: dict) -> TargetResult:
        """Elevate status to WARNING on DNS/content changes vs the stored state."""
        notes: list[str] = []
        new_fp = self._extract(result, "dns", "fingerprint")
        old_fp = state.get("dns_fingerprint")
        if new_fp and old_fp and new_fp != old_fp:
            notes.append("DNS records changed")

        if target.content_hash_check:
            new_sum = self._extract(result, "content", "checksum")
            old_sum = state.get("content_checksum")
            if new_sum and old_sum and new_sum != old_sum:
                notes.append("Content changed")

        if notes and result.status.is_healthy:
            # Attach a synthetic warning check so the change is visible & recorded.
            result.checks.append(
                CheckResult(target=target.name, kind="change", status=Status.WARNING,
                            message="; ".join(notes), details={"changes": notes})
            )
            result.status = Status.WARNING
        return result

    @staticmethod
    def _extract(result: TargetResult, kind: str, key: str) -> str | None:
        for check in result.checks:
            if check.kind == kind:
                value = check.details.get(key)
                return str(value) if value is not None else None
        return None

    @staticmethod
    def _summary(result: TargetResult) -> str:
        parts = [f"{c.kind}:{c.status.value}" for c in result.checks]
        return ", ".join(parts)

    # -- cycles ------------------------------------------------------------ #
    async def run_once(self, targets: list[Target] | None = None) -> list[TargetResult]:
        """Run one full monitoring cycle over the given (or enabled) targets."""
        selected = targets if targets is not None else self.settings.enabled_targets()
        if not selected:
            logger.warning("No enabled targets to monitor.")
            return []

        async def _do(target: Target) -> TargetResult:
            result = await self.check_target(target)
            return await self.process(target, result)

        results = await asyncio.gather(*(_do(t) for t in selected))
        healthy = sum(1 for r in results if r.ok)
        logger.info("Cycle complete: %d/%d targets healthy", healthy, len(results))
        return list(results)

    def purge_old(self) -> int:
        """Delete history older than the configured retention window."""
        return self.db.purge(self.settings.database.retention_days)
