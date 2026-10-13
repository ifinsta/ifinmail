"""Telemetry serializers: the typed wire shapes of the v1 API.

Written out here (not derived from models or service dicts) so refactoring the internals can
never change what an integration receives. Within v1 fields are only added, never removed.
"""

from __future__ import annotations

from ninja import Schema

from backend.apps.core.serializers.health import FingerprintV1


class ErrorEventV1(Schema):
    id: str
    time: str
    severity: str
    action: str
    detail: str
    service: str
    user: str
    correlation_id: str
    fingerprint: str
    source: str


class ErrorPageV1(Schema):
    results: list[ErrorEventV1]
    page: int
    num_pages: int
    total: int


class FingerprintListV1(Schema):
    results: list[FingerprintV1]


class AckIn(Schema):
    status: str = 'ACKED'


class AckV1(Schema):
    success: bool


__all__ = ['AckIn', 'AckV1', 'ErrorEventV1', 'ErrorPageV1', 'FingerprintListV1']
