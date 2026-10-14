"""Telemetry serializers: the typed wire shapes of the v1 API.

Written out here (not derived from models or service dicts) so refactoring the internals can
never change what an integration receives. Within v1 fields are only added, never removed.
"""

from __future__ import annotations

from ninja import Schema

from backend.apps.core.serializers.health import FingerprintV1


class DeliveryVerdictV1(Schema):
    tone: str  # none | ok | watch | bad
    headline: str
    next: str


class DeliveryFiguresV1(Schema):
    sent: int  # accepted by the receiving server (not "reached the inbox")
    deferred: int  # delivery attempts that were postponed (a message can be retried several times)
    bounced: int  # failed for good
    final: int  # sent + bounced
    bounce_rate: float | None  # percent of final outcomes; null when nothing was final
    local_failed: int  # failures delivering into this server's own mailboxes


class DeliveryReasonV1(Schema):
    category: str
    kind: str  # bounced | deferred
    label: str
    hint: str
    count: int
    share: int
    example: str  # the receiver's own words, addresses and IPs removed
    reputation: bool


class DeliveryDestinationV1(Schema):
    domain: str
    provider: str
    sent: int
    deferred: int
    bounced: int
    bounce_rate: float | None


class DeliveryProviderV1(Schema):
    provider: str
    sent: int
    deferred: int
    bounced: int
    bounce_rate: float | None


class DeliverySenderV1(Schema):
    address: str
    sent: int
    deferred: int
    bounced: int
    bounce_rate: float | None


class DeliveryV1(DeliveryFiguresV1):
    period: str
    label: str
    since: str
    until: str
    verdict: DeliveryVerdictV1
    previous: DeliveryFiguresV1
    reasons: list[DeliveryReasonV1]
    destinations: list[DeliveryDestinationV1]
    providers: list[DeliveryProviderV1]
    senders: list[DeliverySenderV1]


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
