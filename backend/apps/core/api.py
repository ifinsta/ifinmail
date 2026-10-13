"""core — api.py: the health routes of the v1 API (urls.py → api.py → viewsets/ contract).

``GET /health`` is the one anonymous operation (liveness for monitors and load balancers). The
detailed reports need ``audit.view``: they run live lookups and name the hosted domains.
The settings re-exports below stay for in-process callers.
"""

from ninja import Router, Status

from backend.apps.accounts.viewsets.auth import ApiRequest, require_scope
from backend.apps.accounts.viewsets.errors import errors
from backend.apps.core.serializers.health import (
    DeliverabilityV1,
    DnsHealthV1,
    HealthFullV1,
    LivenessV1,
)

from . import viewsets
from .viewsets import delete_setting, get_setting, set_setting
from .viewsets import health as ops

router = Router(tags=['health'])


@router.get(
    '/health',
    auth=None,
    response={200: LivenessV1, 503: LivenessV1},
    summary='Liveness (no key needed)',
)
def api_liveness(request: ApiRequest) -> Status[LivenessV1]:
    """200 when the console can reach its database, 503 otherwise. Safe to poll."""
    body, healthy = ops.liveness()
    return Status(200 if healthy else 503, body)


@router.get(
    '/health/full',
    response={200: HealthFullV1, 503: HealthFullV1, **errors()},
    summary='Full health report',
)
@require_scope('audit.view')
def api_health_full(request: ApiRequest) -> Status[HealthFullV1]:
    """Database, cache, certificate and disk, plus the error counters of the last day."""
    body = ops.full()
    return Status(503 if body.status == 'err' else 200, body)


@router.get('/health/dns', response={200: DnsHealthV1, **errors()}, summary='DNS health')
@require_scope('audit.view')
def api_health_dns(request: ApiRequest) -> DnsHealthV1:
    """DNS record checks for every hosted domain."""
    return ops.dns()


@router.get(
    '/health/deliverability',
    response={200: DeliverabilityV1, 503: DeliverabilityV1, **errors()},
    summary='Deliverability checks',
)
@require_scope('audit.view')
def api_health_deliverability(
    request: ApiRequest, domain: str | None = None
) -> Status[DeliverabilityV1]:
    """DNS propagation, blocklists, reverse DNS, port 25 and TLS, checked from outside."""
    body = ops.deliverability(domain)
    return Status(503 if body.status == 'fail' else 200, body)


__all__ = ['delete_setting', 'get_setting', 'router', 'set_setting', 'viewsets']
