"""telemetry — api.py: the error-log routes of the v1 API (urls.py → api.py → viewsets/).

Reads need ``audit.view``. Acknowledging a fingerprint changes what the console shows as open, so
it needs ``system.manage`` (the console's own legacy form used ``audit.view``).
"""

from ninja import Router
from ninja.errors import HttpError

from backend.apps.accounts.viewsets.auth import ApiRequest, actor, require_scope
from backend.apps.accounts.viewsets.errors import errors
from backend.apps.core.platform.services.audit import AuditService
from backend.apps.core.serializers.health import TelemetryStatsV1
from backend.apps.core.telemetry import viewsets as ops
from backend.apps.core.telemetry.serializers import (
    AckIn,
    AckV1,
    DeliveryV1,
    ErrorPageV1,
    FingerprintListV1,
)

router = Router(tags=['telemetry'])


@router.get('/telemetry/errors', response={200: ErrorPageV1, **errors()}, summary='Error events')
@require_scope('audit.view')
def api_errors(
    request: ApiRequest,
    severity: str = '',
    source: str = '',
    q: str = '',
    page: int = 1,
) -> ErrorPageV1:
    """Application errors, newest first. Filter with ``severity``, ``source`` and ``q``."""
    return ops.list_errors(severity=severity, source=source, query=q, page=page)


@router.get(
    '/telemetry/delivery', response={200: DeliveryV1, **errors()}, summary='Outgoing mail delivery'
)
@require_scope('audit.view')
def api_delivery(request: ApiRequest, period: str = 'day') -> DeliveryV1:
    """What happened to the mail this server sent: accepted, retried and failed counts, the bounce
    rate, why it failed (the receiver's own words, classified), where, and from which mailbox.

    ``period`` is ``day``, ``week`` or ``month``. ``sent`` means the receiving server accepted the
    message; it does not say whether it reached the inbox or the spam folder."""
    return ops.delivery(period)


@router.get(
    '/telemetry/stats', response={200: TelemetryStatsV1, **errors()}, summary='Error counters'
)
@require_scope('audit.view')
def api_stats(request: ApiRequest) -> TelemetryStatsV1:
    """Open critical errors and totals of the last 24 hours, with the top fingerprints."""
    return ops.stats()


@router.get(
    '/telemetry/fingerprints',
    response={200: FingerprintListV1, **errors()},
    summary='Error fingerprints',
)
@require_scope('audit.view')
def api_fingerprints(request: ApiRequest) -> FingerprintListV1:
    """The most frequent error fingerprints."""
    return ops.fingerprints()


@router.post(
    '/telemetry/fingerprints/{fingerprint}/ack',
    response={200: AckV1, **errors(404, 422)},
    summary='Acknowledge an error fingerprint',
)
@require_scope('system.manage')
def api_ack(request: ApiRequest, fingerprint: str, payload: AckIn) -> AckV1:
    """Set a fingerprint's status to OPEN, ACKED, RESOLVED or MUTED."""
    status = ops.valid_status(payload.status)
    if status is None:
        raise HttpError(422, 'status must be one of OPEN, ACKED, RESOLVED, MUTED.')
    if not ops.acknowledge(fingerprint.strip(), status):
        raise HttpError(404, 'That fingerprint does not exist.')
    AuditService.record(
        action='api_error_acknowledged', user=actor(request), detail=f'{fingerprint} {status}'
    )
    return AckV1(success=True)


__all__ = ['router']
