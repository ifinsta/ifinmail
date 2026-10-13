"""Health viewset: the server's own checks, shaped into the v1 contract.

Liveness is the only anonymous operation of the API (monitors and load balancers need no key).
The detailed reports run real DNS lookups, port checks and blocklist queries and name the
domains, so they need a key with ``audit.view``.
"""

from __future__ import annotations

from typing import Any

from backend.apps.core.serializers.health import (
    DeliverabilityV1,
    DnsCheckV1,
    DnsHealthV1,
    HealthCheckV1,
    HealthFullV1,
    LivenessV1,
    TelemetryStatsV1,
)
from backend.config.env import primary_domain


def liveness() -> tuple[LivenessV1, bool]:
    """``(body, healthy)``: can the console reach its database."""
    from django.db import connections
    from django.db.utils import OperationalError

    database = 'ok'
    try:
        with connections['default'].cursor() as cursor:
            cursor.execute('SELECT 1')
    except OperationalError:
        database = 'unreachable'
    healthy = database == 'ok'
    return LivenessV1(status='ok' if healthy else 'degraded', database=database), healthy


def full() -> HealthFullV1:
    """Database, cache, certificate and disk, plus the error counters of the last day."""
    from backend.apps.core.platform.services.monitoring import MonitoringService
    from backend.apps.core.telemetry.services.telemetry_service import TelemetryService

    report: dict[str, Any] = MonitoringService.get_full_health()
    stats = TelemetryService.get_stats()
    checks = {
        name: HealthCheckV1(
            status=str(check.get('status', 'err')),
            detail=check.get('detail'),
            days=check.get('days'),
            pct=check.get('pct'),
            free_gb=check.get('free_gb'),
        )
        for name, check in (report.get('checks') or {}).items()
    }
    return HealthFullV1(
        status=str(report.get('status', 'err')),
        timestamp=str(report.get('timestamp', '')),
        checks=checks,
        telemetry=TelemetryStatsV1(**stats),
    )


def dns() -> DnsHealthV1:
    """DNS record checks for every hosted domain (or the configured one)."""
    from backend.apps.core.platform.services.monitoring import MonitoringService
    from backend.apps.domains.services import DomainService

    names = [d.name for d in DomainService.get_all_domains()] or [primary_domain()]
    domains: dict[str, dict[str, DnsCheckV1]] = {}
    for name in names:
        if not name:
            continue
        domains[name] = {
            record: DnsCheckV1(**result)
            for record, result in MonitoringService.check_dns(name).items()
        }
    healthy = all(c.status == 'pass' for records in domains.values() for c in records.values())
    return DnsHealthV1(status='ok' if healthy else 'warn', domains=domains)


def deliverability(domain: str | None) -> DeliverabilityV1:
    """DNS propagation, blocklists, reverse DNS, port 25 and TLS from outside."""
    from backend.apps.core.platform.services.deliverability import DeliverabilityService

    result = DeliverabilityService.run_all_checks(domain=domain or None)
    return DeliverabilityV1.model_validate(result)


__all__ = ['deliverability', 'dns', 'full', 'liveness']
