"""telemetry — viewsets: operations over the error log, shaped into the v1 contract.

Layer: api.py → viewsets/ → serializers/ → services/ → models/.
"""

from __future__ import annotations

from backend.apps.core.serializers.health import FingerprintV1, TelemetryStatsV1
from backend.apps.core.telemetry.serializers import (
    ErrorEventV1,
    ErrorPageV1,
    FingerprintListV1,
)
from backend.apps.core.telemetry.services.telemetry_service import TelemetryService
from backend.apps.core.telemetry.types import ErrorStatus

PAGE_SIZE = 25


def list_errors(*, severity: str, source: str, query: str, page: int) -> ErrorPageV1:
    """One page of error events, newest first, filtered by severity, source and message text."""
    found = TelemetryService.list_events(
        severity=severity.strip().upper(),
        source=source.strip().upper(),
        query=query.strip(),
        page=max(page, 1),
        page_size=PAGE_SIZE,
    )
    return ErrorPageV1(
        results=[ErrorEventV1(**event) for event in found['results']],
        page=int(found['page']),
        num_pages=int(found['num_pages']),
        total=int(found['total']),
    )


def stats() -> TelemetryStatsV1:
    """Open critical errors and totals of the last 24 hours, with the top fingerprints."""
    return TelemetryStatsV1(**TelemetryService.get_stats())


def fingerprints() -> FingerprintListV1:
    """The most frequent error fingerprints."""
    rows = TelemetryService.list_fingerprints(limit=PAGE_SIZE)
    return FingerprintListV1(results=[FingerprintV1(**row) for row in rows])


def valid_status(value: str) -> str | None:
    """The canonical status word, or None when it is not one of ACKED/RESOLVED/MUTED/..."""
    wanted = value.strip().upper()
    return wanted if wanted in {s.value for s in ErrorStatus} else None


def acknowledge(fingerprint_hash: str, status: str) -> bool:
    """Set a fingerprint's status. False when the fingerprint does not exist."""
    return bool(TelemetryService.ack_fingerprint(fingerprint_hash, status))


__all__ = ['acknowledge', 'fingerprints', 'list_errors', 'stats', 'valid_status']
