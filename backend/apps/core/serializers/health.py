"""core — health contract of /api/v1 (typed wire shapes; see ``viewsets.health``)."""

from __future__ import annotations

from ninja import Schema


class LivenessV1(Schema):
    status: str  # "ok" | "degraded"
    database: str  # "ok" | "unreachable"


class HealthCheckV1(Schema):
    status: str  # "ok" | "warn" | "err"
    detail: str | None = None
    days: int | None = None
    pct: float | None = None
    free_gb: float | None = None


class FingerprintV1(Schema):
    hash: str
    exc_type: str
    view_name: str
    count: int
    status: str
    severity_max: str


class TelemetryStatsV1(Schema):
    open_critical_24h: int
    total_24h: int
    top: list[FingerprintV1]


class HealthFullV1(Schema):
    status: str
    timestamp: str
    checks: dict[str, HealthCheckV1]
    telemetry: TelemetryStatsV1


class DnsCheckV1(Schema):
    status: str
    detail: str = ''


class DnsHealthV1(Schema):
    status: str  # "ok" | "warn"
    domains: dict[str, dict[str, DnsCheckV1]]


class DeliverabilityCheckV1(Schema):
    status: str  # "pass" | "warn" | "fail"
    detail: str = ''
    fix: str | None = None


class DnsRecordCheckV1(Schema):
    type: str
    name: str
    status: str
    detail: str = ''


class DnsPropagationV1(DeliverabilityCheckV1):
    records: dict[str, DnsRecordCheckV1] = {}


class ListingV1(Schema):
    listed: bool | None  # None: could not be checked
    detail: str


class BlocklistsV1(DeliverabilityCheckV1):
    listings: dict[str, ListingV1] = {}


class DeliverabilityV1(Schema):
    status: str
    timestamp: str
    domain: str
    server_ip: str
    mail_hostname: str
    dns_propagation: DnsPropagationV1
    blacklists: BlocklistsV1
    reverse_dns: DeliverabilityCheckV1
    port25: DeliverabilityCheckV1
    tls: DeliverabilityCheckV1


class DnsStatusV1(Schema):
    domain: str
    records: dict[str, DnsCheckV1]
